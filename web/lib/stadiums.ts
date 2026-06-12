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
  /** Fence distances (ft) at the foul lines / CF, and wall heights (ft). */
  lfLineFt: number
  cfFt: number
  rfLineFt: number
  lfWallFt: number
  cfWallFt: number
  rfWallFt: number
}

const STADIUMS: StadiumRef[] = [
  { teamAbbrev: 'BAL', stadiumName: 'Oriole Park at Camden Yards', city: 'Baltimore, MD', isDome: false, isRetractable: false, cfBearingDegrees: 97, parkFactorHits: 0.96, parkFactorHrLhb: 0.93, parkFactorHrRhb: 0.98, altitudeFeet: 33, lfLineFt: 333, cfFt: 410, rfLineFt: 318, lfWallFt: 7, cfWallFt: 7, rfWallFt: 21 },
  { teamAbbrev: 'BOS', stadiumName: 'Fenway Park', city: 'Boston, MA', isDome: false, isRetractable: false, cfBearingDegrees: 72, parkFactorHits: 1.04, parkFactorHrLhb: 0.93, parkFactorHrRhb: 1.02, altitudeFeet: 20, lfLineFt: 310, cfFt: 390, rfLineFt: 302, lfWallFt: 37, cfWallFt: 17, rfWallFt: 3 },
  { teamAbbrev: 'NYY', stadiumName: 'Yankee Stadium', city: 'Bronx, NY', isDome: false, isRetractable: false, cfBearingDegrees: 75, parkFactorHits: 1.01, parkFactorHrLhb: 1.18, parkFactorHrRhb: 1.05, altitudeFeet: 55, lfLineFt: 318, cfFt: 408, rfLineFt: 314, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'TBR', stadiumName: 'Tropicana Field', city: 'St. Petersburg, FL', isDome: true, isRetractable: false, cfBearingDegrees: 150, parkFactorHits: 0.95, parkFactorHrLhb: 0.93, parkFactorHrRhb: 0.9, altitudeFeet: 15, lfLineFt: 315, cfFt: 404, rfLineFt: 322, lfWallFt: 9, cfWallFt: 9, rfWallFt: 9 },
  { teamAbbrev: 'TOR', stadiumName: 'Rogers Centre', city: 'Toronto, ON', isDome: false, isRetractable: true, cfBearingDegrees: 200, parkFactorHits: 0.97, parkFactorHrLhb: 1.0, parkFactorHrRhb: 0.97, altitudeFeet: 250, lfLineFt: 328, cfFt: 400, rfLineFt: 328, lfWallFt: 10, cfWallFt: 10, rfWallFt: 10 },
  { teamAbbrev: 'CHW', stadiumName: 'Guaranteed Rate Field', city: 'Chicago, IL', isDome: false, isRetractable: false, cfBearingDegrees: 330, parkFactorHits: 0.98, parkFactorHrLhb: 1.12, parkFactorHrRhb: 1.08, altitudeFeet: 595, lfLineFt: 330, cfFt: 400, rfLineFt: 335, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'CLE', stadiumName: 'Progressive Field', city: 'Cleveland, OH', isDome: false, isRetractable: false, cfBearingDegrees: 80, parkFactorHits: 0.98, parkFactorHrLhb: 0.94, parkFactorHrRhb: 0.94, altitudeFeet: 660, lfLineFt: 325, cfFt: 410, rfLineFt: 325, lfWallFt: 19, cfWallFt: 9, rfWallFt: 8 },
  { teamAbbrev: 'DET', stadiumName: 'Comerica Park', city: 'Detroit, MI', isDome: false, isRetractable: false, cfBearingDegrees: 207, parkFactorHits: 0.99, parkFactorHrLhb: 0.8, parkFactorHrRhb: 0.75, altitudeFeet: 600, lfLineFt: 345, cfFt: 420, rfLineFt: 330, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'HOU', stadiumName: 'Minute Maid Park', city: 'Houston, TX', isDome: false, isRetractable: true, cfBearingDegrees: 233, parkFactorHits: 1.02, parkFactorHrLhb: 1.05, parkFactorHrRhb: 1.08, altitudeFeet: 50, lfLineFt: 315, cfFt: 409, rfLineFt: 326, lfWallFt: 19, cfWallFt: 10, rfWallFt: 7 },
  { teamAbbrev: 'KCR', stadiumName: 'Kauffman Stadium', city: 'Kansas City, MO', isDome: false, isRetractable: false, cfBearingDegrees: 20, parkFactorHits: 1.0, parkFactorHrLhb: 0.92, parkFactorHrRhb: 0.91, altitudeFeet: 750, lfLineFt: 330, cfFt: 410, rfLineFt: 330, lfWallFt: 9, cfWallFt: 9, rfWallFt: 9 },
  { teamAbbrev: 'LAA', stadiumName: 'Angel Stadium', city: 'Anaheim, CA', isDome: false, isRetractable: false, cfBearingDegrees: 227, parkFactorHits: 0.97, parkFactorHrLhb: 0.95, parkFactorHrRhb: 0.97, altitudeFeet: 160, lfLineFt: 347, cfFt: 396, rfLineFt: 350, lfWallFt: 8, cfWallFt: 8, rfWallFt: 18 },
  { teamAbbrev: 'MIN', stadiumName: 'Target Field', city: 'Minneapolis, MN', isDome: false, isRetractable: false, cfBearingDegrees: 20, parkFactorHits: 0.97, parkFactorHrLhb: 0.97, parkFactorHrRhb: 1.0, altitudeFeet: 815, lfLineFt: 339, cfFt: 404, rfLineFt: 328, lfWallFt: 8, cfWallFt: 8, rfWallFt: 23 },
  { teamAbbrev: 'ATH', stadiumName: 'Sutter Health Park', city: 'Sacramento, CA', isDome: false, isRetractable: false, cfBearingDegrees: 2, parkFactorHits: 1.0, parkFactorHrLhb: 1.0, parkFactorHrRhb: 1.0, altitudeFeet: 30, lfLineFt: 330, cfFt: 403, rfLineFt: 325, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'SEA', stadiumName: 'T-Mobile Park', city: 'Seattle, WA', isDome: false, isRetractable: true, cfBearingDegrees: 47, parkFactorHits: 0.97, parkFactorHrLhb: 0.92, parkFactorHrRhb: 0.9, altitudeFeet: 10, lfLineFt: 331, cfFt: 401, rfLineFt: 326, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'TEX', stadiumName: 'Globe Life Field', city: 'Arlington, TX', isDome: false, isRetractable: true, cfBearingDegrees: 200, parkFactorHits: 1.02, parkFactorHrLhb: 1.03, parkFactorHrRhb: 1.08, altitudeFeet: 545, lfLineFt: 329, cfFt: 407, rfLineFt: 326, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'ATL', stadiumName: 'Truist Park', city: 'Cumberland, GA', isDome: false, isRetractable: false, cfBearingDegrees: 22, parkFactorHits: 1.02, parkFactorHrLhb: 1.1, parkFactorHrRhb: 1.12, altitudeFeet: 1050, lfLineFt: 335, cfFt: 400, rfLineFt: 325, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'MIA', stadiumName: 'loanDepot park', city: 'Miami, FL', isDome: false, isRetractable: true, cfBearingDegrees: 240, parkFactorHits: 0.92, parkFactorHrLhb: 0.85, parkFactorHrRhb: 0.82, altitudeFeet: 10, lfLineFt: 335, cfFt: 400, rfLineFt: 335, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'NYM', stadiumName: 'Citi Field', city: 'Flushing, NY', isDome: false, isRetractable: false, cfBearingDegrees: 75, parkFactorHits: 0.96, parkFactorHrLhb: 0.88, parkFactorHrRhb: 0.88, altitudeFeet: 20, lfLineFt: 335, cfFt: 408, rfLineFt: 330, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'PHI', stadiumName: 'Citizens Bank Park', city: 'Philadelphia, PA', isDome: false, isRetractable: false, cfBearingDegrees: 352, parkFactorHits: 1.04, parkFactorHrLhb: 1.1, parkFactorHrRhb: 1.15, altitudeFeet: 20, lfLineFt: 329, cfFt: 401, rfLineFt: 330, lfWallFt: 13, cfWallFt: 6, rfWallFt: 6 },
  { teamAbbrev: 'WSN', stadiumName: 'Nationals Park', city: 'Washington, DC', isDome: false, isRetractable: false, cfBearingDegrees: 195, parkFactorHits: 0.98, parkFactorHrLhb: 1.0, parkFactorHrRhb: 1.0, altitudeFeet: 25, lfLineFt: 336, cfFt: 402, rfLineFt: 335, lfWallFt: 8, cfWallFt: 14, rfWallFt: 8 },
  { teamAbbrev: 'CHC', stadiumName: 'Wrigley Field', city: 'Chicago, IL', isDome: false, isRetractable: false, cfBearingDegrees: 12, parkFactorHits: 1.06, parkFactorHrLhb: 1.05, parkFactorHrRhb: 1.07, altitudeFeet: 600, lfLineFt: 355, cfFt: 400, rfLineFt: 353, lfWallFt: 11, cfWallFt: 11, rfWallFt: 11 },
  { teamAbbrev: 'CIN', stadiumName: 'Great American Ball Park', city: 'Cincinnati, OH', isDome: false, isRetractable: false, cfBearingDegrees: 350, parkFactorHits: 0.99, parkFactorHrLhb: 1.08, parkFactorHrRhb: 1.1, altitudeFeet: 490, lfLineFt: 328, cfFt: 404, rfLineFt: 325, lfWallFt: 12, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'MIL', stadiumName: 'American Family Field', city: 'Milwaukee, WI', isDome: false, isRetractable: true, cfBearingDegrees: 42, parkFactorHits: 1.01, parkFactorHrLhb: 1.03, parkFactorHrRhb: 1.02, altitudeFeet: 635, lfLineFt: 344, cfFt: 400, rfLineFt: 345, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'PIT', stadiumName: 'PNC Park', city: 'Pittsburgh, PA', isDome: false, isRetractable: false, cfBearingDegrees: 27, parkFactorHits: 0.98, parkFactorHrLhb: 0.92, parkFactorHrRhb: 0.9, altitudeFeet: 730, lfLineFt: 325, cfFt: 399, rfLineFt: 320, lfWallFt: 6, cfWallFt: 10, rfWallFt: 21 },
  { teamAbbrev: 'STL', stadiumName: 'Busch Stadium', city: 'St. Louis, MO', isDome: false, isRetractable: false, cfBearingDegrees: 100, parkFactorHits: 0.97, parkFactorHrLhb: 0.93, parkFactorHrRhb: 0.95, altitudeFeet: 465, lfLineFt: 336, cfFt: 400, rfLineFt: 335, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'AZ', stadiumName: 'Chase Field', city: 'Phoenix, AZ', isDome: false, isRetractable: true, cfBearingDegrees: 272, parkFactorHits: 1.03, parkFactorHrLhb: 1.05, parkFactorHrRhb: 1.08, altitudeFeet: 1059, lfLineFt: 330, cfFt: 407, rfLineFt: 334, lfWallFt: 8, cfWallFt: 25, rfWallFt: 8 },
  { teamAbbrev: 'COL', stadiumName: 'Coors Field', city: 'Denver, CO', isDome: false, isRetractable: false, cfBearingDegrees: 220, parkFactorHits: 1.3, parkFactorHrLhb: 1.35, parkFactorHrRhb: 1.38, altitudeFeet: 5200, lfLineFt: 347, cfFt: 415, rfLineFt: 350, lfWallFt: 8, cfWallFt: 8, rfWallFt: 14 },
  { teamAbbrev: 'LAD', stadiumName: 'Dodger Stadium', city: 'Los Angeles, CA', isDome: false, isRetractable: false, cfBearingDegrees: 302, parkFactorHits: 0.98, parkFactorHrLhb: 0.95, parkFactorHrRhb: 1.0, altitudeFeet: 510, lfLineFt: 330, cfFt: 395, rfLineFt: 330, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'SDP', stadiumName: 'Petco Park', city: 'San Diego, CA', isDome: false, isRetractable: false, cfBearingDegrees: 243, parkFactorHits: 0.92, parkFactorHrLhb: 0.82, parkFactorHrRhb: 0.8, altitudeFeet: 60, lfLineFt: 336, cfFt: 396, rfLineFt: 322, lfWallFt: 8, cfWallFt: 8, rfWallFt: 8 },
  { teamAbbrev: 'SFG', stadiumName: 'Oracle Park', city: 'San Francisco, CA', isDome: false, isRetractable: false, cfBearingDegrees: 115, parkFactorHits: 0.93, parkFactorHrLhb: 0.72, parkFactorHrRhb: 0.72, altitudeFeet: 10, lfLineFt: 339, cfFt: 399, rfLineFt: 309, lfWallFt: 8, cfWallFt: 8, rfWallFt: 25 },
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
