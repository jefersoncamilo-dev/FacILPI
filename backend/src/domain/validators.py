import re


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def validate_cpf(cpf: str) -> bool:
    d = only_digits(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    # cálculo dígitos verificadores
    def calc(base: str) -> str:
        s = sum(int(c) * w for c, w in zip(base, range(len(base) + 1, 1, -1)))
        r = (s * 10) % 11
        return str(r if r < 10 else 0)
    d1 = calc(d[:9])
    d2 = calc(d[:9] + d1)
    return d == d[:9] + d1 + d2


def validate_cnpj(cnpj: str) -> bool:
    d = only_digits(cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False
    w1 = [5,4,3,2,9,8,7,6,5,4,3,2]
    w2 = [6,5,4,3,2,9,8,7,6,5,4,3,2]
    def calc(digits: str, weights) -> str:
        s = sum(int(a)*b for a,b in zip(digits, weights))
        r = s % 11
        return '0' if r < 2 else str(11 - r)
    d12 = d[:12]
    d13 = d12 + calc(d12, w1)
    d14 = d13 + calc(d13, w2)
    return d == d14


def validate_cns(cns: str) -> bool:
    d = only_digits(cns)
    if len(d) != 15:
        return False
    # validação CNS: soma ponderada
    soma = sum(int(d[i]) * (15 - i) for i in range(15))
    return soma % 11 == 0


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""))


def validate_password(pwd: str) -> tuple[bool, str]:
    if len(pwd) < 8:
        return False, "Senha deve ter no mínimo 8 caracteres"
    if not re.search(r"[A-Z]", pwd):
        return False, "Senha deve conter letra maiúscula"
    if not re.search(r"[a-z]", pwd):
        return False, "Senha deve conter letra minúscula"
    if not re.search(r"[0-9]", pwd):
        return False, "Senha deve conter número"
    return True, ""
