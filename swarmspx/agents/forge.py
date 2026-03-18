import yaml
from swarmspx.agents.base import TraderAgent
from swarmspx.providers import resolve_tribe_model

class AgentForge:
    """Creates all 24 trader agents from YAML config."""

    def __init__(
        self,
        config_path: str = "config/agents.yaml",
        settings_path: str = "config/settings.yaml"
    ):
        with open(config_path) as f:
            self.agent_config = yaml.safe_load(f)
        with open(settings_path) as f:
            self.settings = yaml.safe_load(f)

    def create_all(self) -> list[TraderAgent]:
        agents = []
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
        return agents
