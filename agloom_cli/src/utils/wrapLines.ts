/**
 * Split text into terminal rows of at most *width* columns (word-aware when possible).
 * Used so ``ScrollableColumn`` scrolls by visible row, not by React element.
 */

export const wrapTextLines = (text: string, width: number): string[] => {
  const w = Math.max(8, width)
  if (!text) return ['']

  const out: string[] = []
  for (const paragraph of text.split('\n')) {
    if (paragraph.length === 0) {
      out.push('')
      continue
    }
    let start = 0
    while (start < paragraph.length) {
      let end = Math.min(start + w, paragraph.length)
      if (end < paragraph.length) {
        const chunk = paragraph.slice(start, end)
        const space = chunk.lastIndexOf(' ')
        if (space > w * 0.3) {
          end = start + space
        }
      }
      const piece = paragraph.slice(start, end).trimEnd()
      out.push(piece.length > 0 ? piece : paragraph.slice(start, start + w))
      start = end
      while (start < paragraph.length && paragraph[start] === ' ') {
        start += 1
      }
    }
  }
  return out.length > 0 ? out : ['']
}
