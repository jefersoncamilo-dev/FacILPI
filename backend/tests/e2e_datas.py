"""Datas do seed E2E, sem relogio implicito (testavel em qualquer instante).

O seed usa UM instante de vigencia (agora - 1 h) para tudo, e deriva cada data
pela mesma regra do backend que a valida:
- PAIS: ``rotina.py`` compara a data UTC da vigencia com ``data_inicial``;
- prescricao: ``medicacao.py`` compara a data local (fuso da programacao) da
  vigencia com ``inicio``.
Usar ``agora.date()`` num e ``agora - 1 h`` no outro falhava entre 00:00 e 01:00
UTC (PAIS) e entre 21:00 e 24:00 de Sao Paulo (prescricao).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def datas_do_cenario(agora_utc: datetime) -> dict[str, datetime | date]:
    vigencia = agora_utc - timedelta(hours=1)
    return {
        "vigencia_inicio": vigencia,
        "pais_data_inicial": vigencia.date(),
        "prescricao_inicio": vigencia.astimezone(FUSO).date(),
    }


def horarios_de_dose(agora_local: datetime) -> list[str] | None:
    """Dois horarios por dia, o primeiro 2 min a frente, no fuso da ILPI/navegador.

    A geracao de doses parte de max(agora, vigencia): horarios fixos deixavam o
    resto do dia sem "dose de hoje". ``None`` quando +2 min vira o dia: o seed
    espera a virada e chama de novo.
    """
    primeiro = agora_local + timedelta(minutes=2)
    if primeiro.date() != agora_local.date():
        return None
    segundo = primeiro + timedelta(hours=12)
    return sorted({primeiro.strftime("%H:%M"), segundo.strftime("%H:%M")})
