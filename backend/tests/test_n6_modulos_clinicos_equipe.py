"""N6 (#206): Platform Superuser nao le ausencias nem escala."""

from types import SimpleNamespace

import pytest

from src.application.security import (
    GLOBAL_SCOPE,
    ILPI_SCOPE,
    _CLINICAL_MODULES,
    _permission_is_allowed,
)


def _contexto(perfil: str, scope: str = GLOBAL_SCOPE):
    return SimpleNamespace(
        perfil=SimpleNamespace(chave=perfil),
        scope=scope,
        ilpi_situacao=None,
    )


@pytest.mark.parametrize("modulo", ["ausencias", "escala"])
def test_modulo_de_equipe_e_clinico(modulo):
    assert modulo in _CLINICAL_MODULES


@pytest.mark.parametrize("chave", ["ausencias:ler", "escala:ler", "escala:gerenciar"])
def test_platform_superuser_nao_le_ausencias_nem_escala(chave):
    modulo = chave.split(":")[0]
    permissao = SimpleNamespace(chave=chave, modulo=modulo)
    for scope in (GLOBAL_SCOPE, ILPI_SCOPE):
        assert _permission_is_allowed(_contexto("platform_superuser", scope), permissao) is False
    assert _permission_is_allowed(_contexto("gestor", ILPI_SCOPE), permissao) is True
