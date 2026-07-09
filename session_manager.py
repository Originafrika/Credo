STATES = [
    "intake",
    "questions",
    "documents",
    "scoring",
    "paywall",
    "report",
    "matching",
]

TRANSITIONS = {
    "intake":     ["questions"],
    "questions":  ["documents", "scoring"],
    "documents":  ["scoring"],
    "scoring":    ["paywall", "report"],
    "paywall":    ["report"],
    "report":     ["matching"],
    "matching":   [],
}


class SessionStateMachine:
    def __init__(self, session_id: str, initial_state: str = "intake"):
        self.session_id = session_id
        self.state = initial_state if initial_state in STATES else "intake"

    def can_transition_to(self, target: str) -> bool:
        return target in TRANSITIONS.get(self.state, [])

    def transition_to(self, target: str) -> str:
        if not self.can_transition_to(target):
            raise ValueError(f"Transition {self.state} → {target} interdite")
        self.state = target
        return self.state

    def allowed_actions(self) -> list[str]:
        mapping = {
            "intake":    ["describe"],
            "questions": ["answer"],
            "documents": ["upload", "skip"],
            "scoring":   [],
            "paywall":   ["pay"],
            "report":    ["view", "download"],
            "matching":  ["transmit"],
        }
        return mapping.get(self.state, [])


class SessionManager:
    MAX_SAFETY_TURNS = 20
    STAGNATION_LIMIT = 3

    def __init__(self, session_id: str, initial_state: str = "intake"):
        self.session_id = session_id
        self.state_machine = SessionStateMachine(session_id, initial_state)
        self.turn_count = 0
        self.last_updated_fields: set = set()
        self.stagnation_count = 0
        self.profile = {}

    @property
    def state(self) -> str:
        return self.state_machine.state

    def record_turn(self, llm_output: dict) -> dict:
        self.turn_count += 1
        profile = llm_output.get("profile", {})
        updated = set(llm_output.get("updated_fields", []))
        for k, v in profile.items():
            if v is not None:
                self.profile[k] = v
        if updated == self.last_updated_fields:
            self.stagnation_count += 1
        else:
            self.stagnation_count = 0
        self.last_updated_fields = updated

        return {
            "profile": profile,
            "updated": updated,
            "stagnation_count": self.stagnation_count,
        }

    def should_stop(self) -> tuple[bool, str]:
        if self.turn_count >= self.MAX_SAFETY_TURNS:
            return True, "circuit_breaker"
        if self.stagnation_count >= self.STAGNATION_LIMIT:
            return True, "stagnation"
        if not self.last_updated_fields and self.profile:
            return True, "nothing_new"
        return False, ""

    def get_progress(self) -> dict:
        total = max(len(self.profile) + 2, 4)
        done = len(self.profile)
        return {"done": done, "total": total}

    def mark_documents_done(self):
        self.state_machine.transition_to("scoring")

    def mark_scoring_done(self):
        self.state_machine.transition_to("paywall")

    def mark_paid(self):
        self.state_machine.transition_to("report")
