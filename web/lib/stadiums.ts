/**
 * Static MLB stadium reference, bundled into the web app for visuals (stadium
 * diagram orientation + HR park-factor shading). Mirrors /data/stadiums.json
 * (the ingester's source of truth). Park factors are Statcast 3-yr rolling
 * averages; cf_bearing_degrees is the compass bearing home plate → CF (0=N, CW).
 *
 * The API only exposes stadium name + dome flag, so we key this by team
 * abbreviation (game.home.abbr) to recover the richer fields client-side.
 */
export interface StadiumRef {
  teamAbbrev: string
  stadiumName: string
  city: string
  isDome: boolean
  isRetractable: boolean
  cfBearingDegrees: number
  parkFactorHits: number
  parkFactorHrLhb: number
  parkFactorHrRhb: number
  altitudeFeet: number
}

const STADIUMS: StadiumRef[] = [
  { teamAbbrev: 'BAL', stadiumName: 'Oriole Park at Camden Yards', city: 'Baltimore, MD', isDome: false, isRetractable: false, cfBearingDegrees: 97, parkFactorHits: 0.96, parkFactorHrLhb: 0.93, parkFactorHrRhb: 0.98, altitudeFeet: 33 },
  { teamAbbrev: 'BOS', stadiumName: 'Fenway Park', city: 'Boston, MA', isDome: false, isRetractable: false, cfBearingDegrees: 72, parkFactorHits: 1.04, parkFactorHrLhb: 0.93, parkFactorHrRhb: 1.02, altitudeFeet: 20 },
  { teamAbbrev: 'NYY', stadiumName: 'Yankee Stadium', city: 'Bronx, NY', isDome: false, isRetractable: false, cfBearingDegrees: 75, parkFactorHits: 1.01, parkFactorHrLhb: 1.18, parkFactorHrRhb: 1.05, altitudeFeet: 55 },
  { teamAbbrev: 'TBR', stadiumName: 'Tropicana Field', city: 'St. Petersburg, FL', isDome: true, isRetractable: false, cfBearingDegrees: 150, parkFactorHits: 0.95, parkFactorHrLhb: 0.93, parkFactorHrRhb: 0.9, altitudeFeet: 15 },
  { teamAbbrev: 'TOR', stadiumName: 'Rogers Centre', city: 'Toronto, ON', isDome: false, isRetractable: true, cfBearingDegrees: 200, parkFactorHits: 0.97, parkFactorHrLhb: 1.0, parkFactorHrRhb: 0.97, altitudeFeet: 250 },
  { teamAbbrev: 'CHW', stadiumName: 'Guaranteed Rate Field', city: 'Chicago, IL', isDome: false, isRetractable: false, cfBearingDegrees: 330, parkFactorHits: 0.98, parkFactorHrLhb: 1.12, parkFactorHrRhb: 1.08, altitudeFeet: 595 },
  { teamAbbrev: 'CLE', stadiumName: 'Progressive Field', city: 'Cleveland, OH', isDome: false, isRetractable: false, cfBearingDegrees: 80, parkFactorHits: 0.98, parkFactorHrLhb: 0.94, parkFactorHrRhb: 0.94, altitudeFeet: 660 },
  { teamAbbrev: 'DET', stadiumName: 'Comerica Park', city: 'Detroit, MI', isDome: false, isRetractable: false, cfBearingDegrees: 207, parkFactorHits: 0.99, parkFactorHrLhb: 0.8, parkFactorHrRhb: 0.75, altitudeFeet: 600 },
  { teamAbbrev: 'HOU', stadiumName: 'Minute Maid Park', city: 'Houston, TX', isDome: false, isRetractable: true, cfBearingDegrees: 233, parkFactorHits: 1.02, parkFactorHrLhb: 1.05, parkFactorHrRhb: 1.08, altitudeFeet: 50 },
  { teamAbbrev: 'KCR', stadiumName: 'Kauffman Stadium', city: 'Kansas City, MO', isDome: false, isRetractable: false, cfBearingDegrees: 20, parkFactorHits: 1.0, parkFactorHrLhb: 0.92, parkFactorHrRhb: 0.91, altitudeFeet: 750 },
  { teamAbbrev: 'LAA', stadiumName: 'Angel Stadium', city: 'Anaheim, CA', isDome: false, isRetractable: false, cfBearingDegrees: 227, parkFactorHits: 0.97, parkFactorHrLhb: 0.95, parkFactorHrRhb: 0.97, altitudeFeet: 160 },
  { teamAbbrev: 'MIN', stadiumName: 'Target Field', city: 'Minneapolis, MN', isDome: false, isRetractable: false, cfBearingDegrees: 20, parkFactorHits: 0.97, parkFactorHrLhb: 0.97, parkFactorHrRhb: 1.0, altitudeFeet: 815 },
  { teamAbbrev: 'ATH', stadiumName: 'Sutter Health Park', city: 'Sacramento, CA', isDome: false, isRetractable: false, cfBearingDegrees: 2, parkFactorHits: 1.0, parkFactorHrLhb: 1.0, parkFactorHrRhb: 1.0, altitudeFeet: 30 },
  { teamAbbrev: 'SEA', stadiumName: 'T-Mobile Park', city: 'Seattle, WA', isDome: false, isRetractable: true, cfBearingDegrees: 47, parkFactorHits: 0.97, parkFactorHrLhb: 0.92, parkFactorHrRhb: 0.9, altitudeFeet: 10 },
  { teamAbbrev: 'TEX', stadiumName: 'Globe Life Field', city: 'Arlington, TX', isDome: false, isRetractable: true, cfBearingDegrees: 200, parkFactorHits: 1.02, parkFactorHrLhb: 1.03, parkFactorHrRhb: 1.08, altitudeFeet: 545 },
  { teamAbbrev: 'ATL', stadiumName: 'Truist Park', city: 'Cumberland, GA', isDome: false, isRetractable: false, cfBearingDegrees: 22, parkFactorHits: 1.02, parkFactorHrLhb: 1.1, parkFactorHrRhb: 1.12, altitudeFeet: 1050 },
  { teamAbbrev: 'MIA', stadiumName: 'loanDepot park', city: 'Miami, FL', isDome: false, isRetractable: true, cfBearingDegrees: 240, parkFactorHits: 0.92, parkFactorHrLhb: 0.85, parkFactorHrRhb: 0.82, altitudeFeet: 10 },
  { teamAbbrev: 'NYM', stadiumName: 'Citi Field', city: 'Flushing, NY', isDome: false, isRetractable: false, cfBearingDegrees: 75, parkFactorHits: 0.96, parkFactorHrLhb: 0.88, parkFactorHrRhb: 0.88, altitudeFeet: 20 },
  { teamAbbrev: 'PHI', stadiumName: 'Citizens Bank Park', city: 'Philadelphia, PA', isDome: false, isRetractable: false, cfBearingDegrees: 352, parkFactorHits: 1.04, parkFactorHrLhb: 1.1, parkFactorHrRhb: 1.15, altitudeFeet: 20 },
  { teamAbbrev: 'WSN', stadiumName: 'Nationals Park', city: 'Washington, DC', isDome: false, isRetractable: false, cfBearingDegrees: 195, parkFactorHits: 0.98, parkFactorHrLhb: 1.0, parkFactorHrRhb: 1.0, altitudeFeet: 25 },
  { teamAbbrev: 'CHC', stadiumName: 'Wrigley Field', city: 'Chicago, IL', isDome: false, isRetractable: false, cfBearingDegrees: 12, parkFactorHits: 1.06, parkFactorHrLhb: 1.05, parkFactorHrRhb: 1.07, altitudeFeet: 600 },
  { teamAbbrev: 'CIN', stadiumName: 'Great American Ball Park', city: 'Cincinnati, OH', isDome: false, isRetractable: false, cfBearingDegrees: 350, parkFactorHits: 0.99, parkFactorHrLhb: 1.08, parkFactorHrRhb: 1.1, altitudeFeet: 490 },
  { teamAbbrev: 'MIL', stadiumName: 'American Family Field', city: 'Milwaukee, WI', isDome: false, isRetractable: true, cfBearingDegrees: 42, parkFactorHits: 1.01, parkFactorHrLhb: 1.03, parkFactorHrRhb: 1.02, altitudeFeet: 635 },
  { teamAbbrev: 'PIT', stadiumName: 'PNC Park', city: 'Pittsburgh, PA', isDome: false, isRetractable: false, cfBearingDegrees: 27, parkFactorHits: 0.98, parkFactorHrLhb: 0.92, parkFactorHrRhb: 0.9, altitudeFeet: 730 },
  { teamAbbrev: 'STL', stadiumName: 'Busch Stadium', city: 'St. Louis, MO', isDome: false, isRetractable: false, cfBearingDegrees: 100, parkFactorHits: 0.97, parkFactorHrLhb: 0.93, parkFactorHrRhb: 0.95, altitudeFeet: 465 },
  { teamAbbrev: 'AZ', stadiumName: 'Chase Field', city: 'Phoenix, AZ', isDome: false, isRetractable: true, cfBearingDegrees: 272, parkFactorHits: 1.03, parkFactorHrLhb: 1.05, parkFactorHrRhb: 1.08, altitudeFeet: 1059 },
  { teamAbbrev: 'COL', stadiumName: 'Coors Field', city: 'Denver, CO', isDome: false, isRetractable: false, cfBearingDegrees: 220, parkFactorHits: 1.3, parkFactorHrLhb: 1.35, parkFactorHrRhb: 1.38, altitudeFeet: 5200 },
  { teamAbbrev: 'LAD', stadiumName: 'Dodger Stadium', city: 'Los Angeles, CA', isDome: false, isRetractable: false, cfBearingDegrees: 302, parkFactorHits: 0.98, parkFactorHrLhb: 0.95, parkFactorHrRhb: 1.0, altitudeFeet: 510 },
  { teamAbbrev: 'SDP', stadiumName: 'Petco Park', city: 'San Diego, CA', isDome: false, isRetractable: false, cfBearingDegrees: 243, parkFactorHits: 0.92, parkFactorHrLhb: 0.82, parkFactorHrRhb: 0.8, altitudeFeet: 60 },
  { teamAbbrev: 'SFG', stadiumName: 'Oracle Park', city: 'San Francisco, CA', isDome: false, isRetractable: false, cfBearingDegrees: 115, parkFactorHits: 0.93, parkFactorHrLhb: 0.72, parkFactorHrRhb: 0.72, altitudeFeet: 10 },
]

// Common abbreviation variants → our canonical key, so a differing API abbr
// (e.g. MLB's "OAK"/"ARI") still resolves to the right park.
const ABBR_ALIASES: Record<string, string> = {
  OAK: 'ATH',
  ARI: 'AZ',
  KC: 'KCR',
  TB: 'TBR',
  SF: 'SFG',
  SD: 'SDP',
  WSH: 'WSN',
  CWS: 'CHW',
}

const BY_ABBR = new Map(STADIUMS.map((s) => [s.teamAbbrev, s]))

/** Look up a park by the home team's abbreviation, tolerating common variants. */
export function getStadiumByAbbr(abbr: string | null | undefined): StadiumRef | null {
  if (!abbr) return null
  const key = abbr.toUpperCase()
  return BY_ABBR.get(key) ?? BY_ABBR.get(ABBR_ALIASES[key] ?? '') ?? null
}
