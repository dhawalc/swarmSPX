import logging
from pathlib import Path

import yaml

from swarmspx.agents.base import TraderAgent
from swarmspx.providers import resolve_tribe_model

logger = logging.getLogger(__name__)

MAX_TOTAL_AGENTS = 30


class AgentForge:
    """Creates trader agents from YAML config (base 24 + custom)."""

    def __init__(
        self,
        config_path: str = "config/agents.yaml",
        settings_path: str = "config/settings.yaml",
        custom_path: str = "config/custom_agents.yaml",
    ):
        with open(config_path) as f:
            self.agent_config = yaml.safe_load(f)
        with open(settings_path) as f:
            self.settings = yaml.safe_load(f)
        self.custom_path = Path(custom_path)
        self._custom_agents: list[dict] = self._load_custom()

    def _load_custom(self) -> list[dict]:
        """Load custom agent definitions from YAML (if file exists)."""
        if not self.custom_path.exists():
            return []
        try:
            with open(self.custom_path) as f:
                data = yaml.safe_load(f) or {}
            agents = data.get("agents", [])
            return agents if isinstance(agents, list) else []
        except Exception as e:
            logger.warning("Failed to load custom agents: %s", e)
            return []

    def _save_custom(self) -> None:
        """Persist current custom agents to YAML."""
        with open(self.custom_path, "w") as f:
            yaml.safe_dump({"agents": self._custom_agents}, f, default_flow_style=False)

    def add_custom_agent(self, agent_def: dict) -> dict:
        """Add a custom agent definition. Returns the added agent dict.

        Raises ValueError if the agent cap would be exceeded or id is duplicate.
        """
        base_count = sum(
            len(tribe) for tribe in self.agent_config["tribes"].values()
        )
        if base_count + len(self._custom_agents) >= MAX_TOTAL_AGENTS:
            raise ValueError(
                f"Agent cap reached ({MAX_TOTAL_AGENTS}). Remove a custom agent first."
            )

        new_id = agent_def.get("id", "")
        if not new_id:
            raise ValueError("Agent must have an 'id' field.")
        # Check duplicate across base + custom
        all_ids = {a["id"] for t in self.agent_config["tribes"].values() for a in t}
        all_ids.update(a["id"] for a in self._custom_agents)
        if new_id in all_ids:
            raise ValueError(f"Agent id '{new_id}' already exists.")

        for field in ("name", "persona", "specialty", "bias"):
            if not agent_def.get(field):
                raise ValueError(f"Agent must have a '{field}' field.")

        clean = {
            "id": new_id,
            "name": agent_def["name"],
            "tribe": agent_def.get("tribe", "technical"),
            "persona": agent_def["persona"],
            "specialty": agent_def["specialty"],
            "bias": agent_def["bias"],
        }
        self._custom_agents.append(clean)
        self._save_custom()
        return clean

    def remove_custom_agent(self, agent_id: str) -> bool:
        """Remove a custom agent by id. Returns True if found and removed."""
        before = len(self._custom_agents)
        self._custom_agents = [a for a in self._custom_agents if a["id"] != agent_id]
        if len(self._custom_agents) < before:
            self._save_custom()
            return True
        return False

    def get_custom_agents(self) -> list[dict]:
        return list(self._custom_agents)

    def create_all(self) -> list[TraderAgent]:
        agents = []
        # Base agents (from tribes)
        for tribe_name, tribe_agents in self.agent_config["tribes"].items():
            mcfg = resolve_tribe_model(tribe_name, self.settings)
            for agent_def in tribe_agents:
                agent = TraderAgent(
                    agent_id=agent_def["id"],
                    name=agent_def["name"],
                    persona=agent_def["persona"],
                    specialty=agent_def["specialty"],
                    bias=agent_def["bias"],
                    ollama_base_url=mcfg["base_url"],
                    model=mcfg["model"],
                    tribe=tribe_name,
                    api_key=mcfg["api_key"],
                    use_claude_cli=mcfg["use_claude_cli"],
                    claude_model=mcfg["claude_model"],
                )
                agents.append(agent)

        # Custom agents (merged after base, capped at MAX_TOTAL_AGENTS)
        slots = MAX_TOTAL_AGENTS - len(agents)
        for agent_def in self._custom_agents[:slots]:
            tribe = agent_def.get("tribe", "technical")
            mcfg = resolve_tribe_model(tribe, self.settings)
            agent = TraderAgent(
                agent_id=agent_def["id"],
                name=agent_def["name"],
                persona=agent_def["persona"],
                specialty=agent_def["specialty"],
                bias=agent_def["bias"],
                ollama_base_url=mcfg["base_url"],
                model=mcfg["model"],
                tribe=tribe,
                api_key=mcfg["api_key"],
                use_claude_cli=mcfg["use_claude_cli"],
                claude_model=mcfg["claude_model"],
            )
            agents.append(agent)

        if len(self._custom_agents) > slots:
            logger.warning(
                "Custom agent cap exceeded: %d defined, %d slots available",
                len(self._custom_agents),
                slots,
            )

        return agents
