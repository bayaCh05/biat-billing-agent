"""Chargement et accès au fichier config/client_templates.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class IssuerConfig:
    name:    str
    tax_id:  str
    address: str = ""
    phone:   str = ""
    email:   str = ""
    rib:     str = ""


@dataclass
class ClientConfig:
    id:                 str
    name:               str
    tax_id:             str
    address:            str = ""
    payment_terms_days: int = 30


@dataclass
class ServiceTemplate:
    id:                  str
    label:               str
    description:         str
    compte_produit:      str
    tva_rate:            float
    recurrence:          str
    default_unit_price:  float
    default_quantity:    float
    default_client_id:   str = ""


class TemplateLoader:
    """Charge et expose le registre clients + les modèles de services."""

    def __init__(self, path: str | Path) -> None:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        raw_issuer = data.get("issuer", {})
        self._issuer = IssuerConfig(
            name=raw_issuer.get("name", ""),
            tax_id=raw_issuer.get("tax_id", ""),
            address=raw_issuer.get("address", ""),
            phone=raw_issuer.get("phone", ""),
            email=raw_issuer.get("email", ""),
            rib=raw_issuer.get("rib", ""),
        )

        self._clients: dict[str, ClientConfig] = {
            c["id"]: ClientConfig(
                id=c["id"],
                name=c["name"],
                tax_id=c["tax_id"],
                address=c.get("address", ""),
                payment_terms_days=c.get("payment_terms_days", 30),
            )
            for c in data.get("clients", [])
        }

        self._templates: dict[str, ServiceTemplate] = {
            t["id"]: ServiceTemplate(
                id=t["id"],
                label=t["label"],
                description=str(t.get("description", t["label"])).strip(),
                compte_produit=t["compte_produit"],
                tva_rate=float(t.get("tva_rate", 19.0)),
                recurrence=t.get("recurrence", "ponctuelle"),
                default_unit_price=float(t.get("default_unit_price", 0.0)),
                default_quantity=float(t.get("default_quantity", 1.0)),
                default_client_id=t.get("default_client_id", ""),
            )
            for t in data.get("service_templates", [])
        }

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def issuer(self) -> IssuerConfig:
        return self._issuer

    def get_client(self, client_id: str) -> ClientConfig:
        if client_id not in self._clients:
            raise KeyError(f"Client inconnu : '{client_id}'")
        return self._clients[client_id]

    def list_clients(self) -> list[ClientConfig]:
        return list(self._clients.values())

    def get_template(self, template_id: str) -> ServiceTemplate:
        if template_id not in self._templates:
            raise KeyError(f"Modèle de service inconnu : '{template_id}'")
        return self._templates[template_id]

    def list_templates(self) -> list[ServiceTemplate]:
        return list(self._templates.values())
