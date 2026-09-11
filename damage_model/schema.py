from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True, order=True)
class Card:
    id: str
    upgrade: int = 0
    enchantment_id: str = ''
    enchantment_amount: int = 0
    persistent_state: tuple[tuple[str, int], ...] = ()

    def __post_init__(self):
        state = self.persistent_state
        items = list(state.items()) if isinstance(state, dict) else list(state)
        if any(len(item) != 2 for item in items) or len({item[0] for item in items}) != len(items):
            raise ValueError('Invalid or duplicate persistent card fields')
        object.__setattr__(self, 'persistent_state', tuple(sorted(tuple(item) for item in items)))

    def to_dict(self):
        result = {'id': self.id, 'upgrade': self.upgrade}
        if self.enchantment_id or self.enchantment_amount:
            result.update(enchantment_id=self.enchantment_id, enchantment_amount=self.enchantment_amount)
        if self.persistent_state:
            result['persistent_state'] = dict(self.persistent_state)
        return result


@dataclass(frozen=True)
class Relic:
    id: str
    # Sorted key/value pairs. Relic acquisition order is retained by Build.relics.
    state: tuple[tuple[str, int | bool], ...] = ()


@dataclass(frozen=True)
class Build:
    act_id: str
    act: int
    cards: tuple[Card, ...]
    relics: tuple[Relic, ...]
    ancient_history: tuple[tuple[int, str, str], ...]
    family: str
    generation: int = 0
    parent: str | None = None
    mutation: str = "initial"

    def state(self):
        return {"act_id": self.act_id, "act": self.act,
                "cards": [c.to_dict() for c in sorted(self.cards)],
                "relics": [asdict(r) for r in self.relics],
                "ancient_history": self.ancient_history}

    @property
    def id(self):
        return digest(self.state())

    @property
    def split(self):
        bucket = int(digest(self.family)[:8], 16) % 100
        return "train" if bucket < 80 else "validation" if bucket < 90 else "test"

    def to_dict(self):
        return {**asdict(self), 'cards': [c.to_dict() for c in self.cards]}

    @classmethod
    def from_dict(cls, data):
        values = dict(data)
        values["cards"] = tuple(Card(**c) for c in values["cards"])
        values["relics"] = tuple(Relic(r["id"], tuple((str(k), v) for k, v in r["state"]))
                                   for r in values["relics"])
        values["ancient_history"] = tuple(tuple(h) for h in values["ancient_history"])
        return cls(**values)
