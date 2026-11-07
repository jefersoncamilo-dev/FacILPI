/** Texto para comparação: sem acento, sem maiúscula e com espaços simples. */
export function normalizar(texto: string): string {
  return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim()
}

/** `termo` aparece em `texto`, ignorando acento e maiúscula. Termo vazio casa com tudo. */
export function contem(texto: string, termo: string): boolean {
  return normalizar(texto).includes(normalizar(termo))
}
