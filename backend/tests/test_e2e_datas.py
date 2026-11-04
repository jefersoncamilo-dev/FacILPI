"""Datas do seed E2E perto da meia-noite UTC e de Brasilia.

Predicados copiados das validacoes do backend:
- ``rotina.py``: ``vigencia_inicio`` (data UTC) nao pode ser anterior a ``data_inicial`` do PAIS;
- ``medicacao.py``: a data local da vigencia nao pode ser anterior ao ``inicio`` da prescricao.
"""
from datetime import datetime, timedelta, timezone

import pytest

from tests.e2e_datas import FUSO, datas_do_cenario, horarios_de_dose

UTC = timezone.utc
INSTANTES = [
    datetime(2026, 11, 3, 23, 59, tzinfo=UTC),   # 20:59 SP
    datetime(2026, 11, 4, 0, 0, tzinfo=UTC),     # virada UTC
    datetime(2026, 11, 4, 0, 10, tzinfo=UTC),    # falha do PR #231
    datetime(2026, 11, 4, 0, 59, tzinfo=UTC),
    datetime(2026, 11, 4, 1, 0, tzinfo=UTC),
    datetime(2026, 11, 3, 23, 5, tzinfo=UTC),    # falha do PR #228 (20:05 SP)
    datetime(2026, 11, 4, 0, 30, tzinfo=UTC),    # 21:30 SP: data UTC ja e amanha
    datetime(2026, 11, 4, 2, 59, tzinfo=UTC),    # 23:59 SP
    datetime(2026, 11, 4, 3, 0, tzinfo=UTC),     # virada de Brasilia
    datetime(2026, 11, 4, 3, 30, tzinfo=UTC),    # 00:30 SP
    datetime(2026, 11, 4, 4, 0, tzinfo=UTC),     # 01:00 SP
    datetime(2026, 11, 4, 15, 0, tzinfo=UTC),    # meio do dia
]


@pytest.mark.parametrize("agora", INSTANTES, ids=lambda d: d.strftime("%H%MZ"))
def test_datas_respeitam_as_regras_do_backend(agora):
    datas = datas_do_cenario(agora)
    vigencia = datas["vigencia_inicio"]
    assert vigencia <= agora
    assert not vigencia.date() < datas["pais_data_inicial"]
    assert not vigencia.astimezone(FUSO).date() < datas["prescricao_inicio"]


def test_formula_antiga_falhava_na_virada_utc():
    agora = datetime(2026, 11, 4, 0, 10, tzinfo=UTC)
    assert (agora - timedelta(hours=1)).date() < agora.date()  # o 422 do PR #231


@pytest.mark.parametrize("agora", INSTANTES, ids=lambda d: d.strftime("%H%MZ"))
def test_ha_dose_ainda_hoje_no_fuso_do_navegador(agora):
    local = agora.astimezone(FUSO)
    horarios = horarios_de_dose(local)
    if local.hour == 23 and local.minute >= 58:
        assert horarios is None  # o seed espera a virada
        return
    assert horarios is not None and len(horarios) == 2
    primeiro = min(datetime.combine(local.date(), datetime.strptime(h, "%H:%M").time(), FUSO) for h in horarios
                   if datetime.strptime(h, "%H:%M").time() > local.time())
    assert primeiro.date() == local.date()


def test_virada_de_brasilia_espera():
    assert horarios_de_dose(datetime(2026, 11, 3, 23, 59, tzinfo=FUSO)) is None
