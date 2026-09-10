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

    def to_dict(self):
        result = {'id': self.id, 'upgrade': self.upgrade}
        if self.enchantment_id or self.enchantment_amount:
            result.update(enchantment_id=self.enchantment_id, enchantment_amount=self.enchantment_amount)
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
