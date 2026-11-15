import type { ReactElement } from 'react'

const P: Record<string, ReactElement> = {
  eye: <><path d="M2 11s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z" /><circle cx="11" cy="11" r="2.6" /></>,
  eyeoff: <><path d="M3 3l16 16" /><path d="M8.2 5.6A9 9 0 0111 5c5.5 0 9 6 9 6a15 15 0 01-3 3.5M5.6 7.6A15 15 0 002 11s3.5 6 9 6a9 9 0 003.3-.7" /><path d="M9 9.2a2.6 2.6 0 003.8 3.6" /></>,
  code: <path d="M7.5 6L3 11l4.5 5M14.5 6L19 11l-4.5 5M12.5 4.5l-3 13" />,
  gear: <><circle cx="11" cy="11" r="2.8" /><path d="M11 2.5v2.2M11 17.3v2.2M2.5 11h2.2M17.3 11h2.2M5 5l1.6 1.6M15.4 15.4L17 17M17 5l-1.6 1.6M6.6 15.4L5 17" /></>,
  x: <path d="M5 5l12 12M17 5L5 17" />,
  plus: <path d="M11 4v14M4 11h14" />,
  chevron: <path d="M7 4.5l6 6.5-6 6.5" />,
  play: <path d="M6 4l12 7-12 7z" />,
  save: <><path d="M4 4h11l3 3v11H4z" /><path d="M7 4v5h7V4M7 18v-6h8v6" /></>,
  bell: <><path d="M5 16h12l-1.5-2.5V9a4.5 4.5 0 00-9 0v4.5z" /><path d="M9 18.5a2 2 0 004 0" /></>,
  expand: <path d="M4 8V4h4M18 8V4h-4M4 14v4h4M18 14v4h-4" />,
  shrink: <path d="M8 4v4H4M14 4v4h4M8 18v-4H4M14 18v-4h4" />,
  star: <path d="M11 3l2.4 5 5.4.7-4 3.8 1 5.4L11 15.2 6.2 17.9l1-5.4-4-3.8 5.4-.7z" />,
  trash: <path d="M5 7h12M9 7V5h4v2M7 7l1 11h6l1-11" />,
}

export default function Icon({ name, size = 16 }: { name: keyof typeof P | string; size?: number }) {
  return (
    <svg viewBox="0 0 22 22" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {P[name]}
    </svg>
  )
}
