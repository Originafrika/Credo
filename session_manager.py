class SessionManager:
    MAX_SAFETY_TURNS = 20
    STAGNATION_LIMIT = 3

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.turn_count = 0
        self.last_updated_fields: set = set()
        self.stagnation_count = 0
        self.profile = {}

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
