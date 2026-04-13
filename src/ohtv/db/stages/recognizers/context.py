"""Context for action recognizers."""

from dataclasses import dataclass, field


@dataclass
class RecognizerContext:
    """Context passed to recognizers for stateful processing.
    
    Provides access to surrounding events and accumulated state
    that recognizers may need for correlation.
    
    Attributes:
        conversation_id: ID of the conversation being processed
        events: All events in the conversation (for lookups)
        current_index: Index of current event in events list
        state: Mutable dict for recognizers to share state
    """
    conversation_id: str
    events: list[dict]
    current_index: int = 0
    state: dict = field(default_factory=dict)
    
    @property
    def current_event(self) -> dict:
        """Get the current event."""
        return self.events[self.current_index]
    
    @property
    def next_event(self) -> dict | None:
        """Get the next event (usually an observation), or None."""
        if self.current_index + 1 < len(self.events):
            return self.events[self.current_index + 1]
        return None
    
    @property
    def prev_event(self) -> dict | None:
        """Get the previous event, or None."""
        if self.current_index > 0:
            return self.events[self.current_index - 1]
        return None
    
    def get_observation_for_action(self) -> dict | None:
        """Get the observation event following the current action.
        
        Returns the next event if it's an ObservationEvent, else None.
        """
        next_ev = self.next_event
        if next_ev and next_ev.get("kind") == "ObservationEvent":
            return next_ev
        return None
    
    def get_observation_content(self) -> str:
        """Get the text content from the observation following current action."""
        obs_event = self.get_observation_for_action()
        if not obs_event:
            return ""
        
        obs = obs_event.get("observation", {})
        content = obs.get("content", [])
        
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(texts)
        return ""
    
    def get_observation_exit_code(self) -> int | None:
        """Get exit code from observation following current action."""
        obs_event = self.get_observation_for_action()
        if not obs_event:
            return None
        return obs_event.get("observation", {}).get("exit_code")
    
    def action_succeeded(self) -> bool:
        """Check if the current action's observation indicates success.
        
        For terminal actions, this checks exit_code == 0.
        For other actions, returns True if there's an observation.
        """
        exit_code = self.get_observation_exit_code()
        if exit_code is not None:
            return exit_code == 0
        # Non-terminal actions: assume success if observation exists
        return self.get_observation_for_action() is not None
