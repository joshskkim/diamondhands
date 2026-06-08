'use client'

import type { Weather } from '@/lib/types'
import type { StadiumRef } from '@/lib/stadiums'
import { Chip, microLabel } from './ui'

function degreesToCardinal(deg: number): string {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return dirs[Math.round(deg / 45) % 8]
}

/**
 * Translate a park HR factor into a fill. Hitter-friendly (>1) trends warm
 * (rose), pitcher-friendly (<1) trends cool (cyan); opacity scales with how far
 * the park deviates from neutral, so average parks read faint.
 */
function pfFill(factor: number): string {
  const d = factor - 1
  const op = Math.min(0.55, Math.abs(d) * 2.6).toFixed(2)
  return d >= 0 ? `rgba(244,63,94,${op})` : `rgba(34,211,238,${op})`
}

function pfLabel(factor: number): string {
  if (factor >= 1.08) return 'HR-friendly'
  if (factor >= 1.02) return 'slightly HR+'
  if (factor <= 0.92) return 'HR-suppressing'
  if (factor <= 0.98) return 'slightly HR−'
  return 'neutral'
}

/**
 * Stylized, data-driven ballpark. Pull-side outfield shading tracks the park's
 * HR factors (LHB pull = right field, RHB pull = left field), a compass shows
 * the real CF bearing, and a wind vane reflects current conditions. The dashed
 * center overlay marks where real hit-spray / hot-zone data will render once the
 * batted-ball pipeline lands.
 */
export function StadiumDiagram({
  stadium,
  stadiumName,
  isDome,
  weather,
}: {
  stadium: StadiumRef | null
  stadiumName: string
  isDome: boolean
  weather: Weather
}) {
  // RHB pull to LF (left half); LHB pull to RF (right half).
  const lfFill = stadium ? pfFill(stadium.parkFactorHrRhb) : 'rgba(255,255,255,0.03)'
  const rfFill = stadium ? pfFill(stadium.parkFactorHrLhb) : 'rgba(255,255,255,0.03)'

  const dome = isDome || stadium?.isDome
  const showWind =
    !dome && weather.windDirDeg != null && weather.windMph != null

  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl p-5">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-lg font-semibold tracking-tight text-zinc-100">{stadiumName}</h2>
        <span className={microLabel}>Park &amp; conditions</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-[260px_1fr] gap-5">
        {/* field */}
        <div className="relative mx-auto w-full max-w-[260px]">
          <svg viewBox="0 0 320 280" className="w-full h-auto" role="img" aria-label="Ballpark diagram">
            {/* grass base */}
            <path d="M160 250 L19 109 Q60 34 160 46 Q260 34 301 109 Z" fill="#101a14" stroke="rgba(255,255,255,0.08)" />
            {/* RHB pull (left field) */}
            <path d="M160 250 L19 109 Q60 34 160 46 Z" fill={lfFill} />
            {/* LHB pull (right field) */}
            <path d="M160 250 L160 46 Q260 34 301 109 Z" fill={rfFill} />
            {/* outfield wall */}
            <path d="M19 109 Q60 34 160 46 Q260 34 301 109" fill="none" stroke="rgba(255,255,255,0.25)" strokeWidth="2" />
            {/* foul lines */}
            <line x1="160" y1="250" x2="19" y2="109" stroke="rgba(255,255,255,0.3)" strokeWidth="1.5" />
            <line x1="160" y1="250" x2="301" y2="109" stroke="rgba(255,255,255,0.3)" strokeWidth="1.5" />
            {/* center line (home → CF) */}
            <line x1="160" y1="250" x2="160" y2="46" stroke="rgba(255,255,255,0.08)" strokeDasharray="3 4" />
            {/* infield diamond */}
            <polygon points="160,250 192,218 160,186 128,218" fill="#1c2b20" stroke="rgba(255,255,255,0.2)" strokeWidth="1.2" />
            {/* home plate */}
            <circle cx="160" cy="250" r="3" fill="#fafafa" />

            {/* spray / hot-zone placeholder */}
            <g opacity="0.6">
              <rect x="92" y="92" width="136" height="74" rx="8" fill="none" stroke="rgba(34,211,238,0.4)" strokeDasharray="5 5" />
              <text x="160" y="124" textAnchor="middle" fill="#67e8f9" fontSize="10" fontWeight="600">
                Hit spray &amp; hot zones
              </text>
              <text x="160" y="140" textAnchor="middle" fill="#52525b" fontSize="9">
                coming soon
              </text>
            </g>

            {/* side labels */}
            <text x="36" y="150" fill="#71717a" fontSize="9">LF</text>
            <text x="276" y="150" fill="#71717a" fontSize="9">RF</text>
            <text x="160" y="40" textAnchor="middle" fill="#71717a" fontSize="9">CF</text>

            {/* wind vane */}
            {showWind && (
              <g transform="translate(290, 250)">
                <circle r="16" fill="rgba(0,0,0,0.4)" stroke="rgba(255,255,255,0.12)" />
                <g transform={`rotate(${weather.windDirDeg})`}>
                  <line x1="0" y1="8" x2="0" y2="-8" stroke="#67e8f9" strokeWidth="1.5" />
                  <polygon points="0,-11 -3,-5 3,-5" fill="#67e8f9" />
                </g>
                <text x="0" y="28" textAnchor="middle" fill="#71717a" fontSize="8">wind</text>
              </g>
            )}

            {/* compass */}
            <g transform="translate(30, 250)">
              <circle r="16" fill="rgba(0,0,0,0.4)" stroke="rgba(255,255,255,0.12)" />
              {stadium && (
                <g transform={`rotate(${stadium.cfBearingDegrees})`}>
                  <line x1="0" y1="0" x2="0" y2="-11" stroke="#a1a1aa" strokeWidth="1.5" />
                  <polygon points="0,-14 -3,-8 3,-8" fill="#a1a1aa" />
                </g>
              )}
              <text x="0" y="-18" textAnchor="middle" fill="#71717a" fontSize="7">N</text>
            </g>
          </svg>
        </div>

        {/* annotations */}
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {dome ? (
              <Chip tone="info">{stadium?.isRetractable ? 'Retractable roof' : 'Dome'}</Chip>
            ) : (
              stadium?.isRetractable && <Chip tone="info">Retractable roof</Chip>
            )}
            {stadium && stadium.altitudeFeet >= 1000 && (
              <Chip tone="projected">{stadium.altitudeFeet.toLocaleString()} ft elevation</Chip>
            )}
            {showWind && (
              <Chip>
                {weather.tempF != null && `${weather.tempF}°F · `}
                {weather.windMph} mph from {degreesToCardinal(weather.windDirDeg!)}
              </Chip>
            )}
            {dome && <Chip>Climate controlled</Chip>}
          </div>

          {stadium ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <div>
                <dt className={microLabel}>Park (hits)</dt>
                <dd className="font-mono tabular-nums text-zinc-200">
                  {stadium.parkFactorHits.toFixed(2)}
                </dd>
              </div>
              <div>
                <dt className={microLabel}>Elevation</dt>
                <dd className="font-mono tabular-nums text-zinc-200">
                  {stadium.altitudeFeet.toLocaleString()} ft
                </dd>
              </div>
              <div>
                <dt className={microLabel}>HR · vs RHB (LF)</dt>
                <dd className="font-mono tabular-nums text-zinc-200">
                  {stadium.parkFactorHrRhb.toFixed(2)}{' '}
                  <span className="text-[10px] text-zinc-500">{pfLabel(stadium.parkFactorHrRhb)}</span>
                </dd>
              </div>
              <div>
                <dt className={microLabel}>HR · vs LHB (RF)</dt>
                <dd className="font-mono tabular-nums text-zinc-200">
                  {stadium.parkFactorHrLhb.toFixed(2)}{' '}
                  <span className="text-[10px] text-zinc-500">{pfLabel(stadium.parkFactorHrLhb)}</span>
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-zinc-500">No park-factor data for this venue.</p>
          )}

          <p className="text-[11px] text-zinc-500 leading-relaxed">
            Outfield shading reflects this park&apos;s home-run factors by batter
            hand — warmer is more HR-friendly. Spray charts and hitting hot zones
            land here once batted-ball data is wired up.
          </p>
        </div>
      </div>
    </div>
  )
}
