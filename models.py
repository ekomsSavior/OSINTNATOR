"""Serializable research models; no UI or collector side effects."""
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class OSINTQuery:
    first: str = ""; last: str = ""; username: str = ""; email: str = ""; phone: str = ""
    address1: str = ""; city: str = ""; state: str = ""; zip: str = ""; domain: str = ""
    @property
    def full_name(self) -> str:
        parts = [self.first.strip(), self.last.strip()]
        return " ".join([p for p in parts if p])
    def to_ordered_dict(self) -> Dict[str,str]:
        return {
            "first": self.first or "","last": self.last or "",
            "username": self.username or "","email": self.email or "",
            "phone": self.phone or "","address1": self.address1 or "",
            "city": self.city or "","state": self.state or "","zip": self.zip or "", "domain": self.domain or ""
        }

@dataclass
class OSINTHit:
    site: str; title: str; snippet: str; url: str; raw: Dict[str, Any]
