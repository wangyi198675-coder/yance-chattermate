import type { PersonProfileProjection } from '@/types/people'

const ZH_LOCATION_ALIASES: Readonly<Record<string, string>> = Object.freeze({
  Berlin: '柏林',
  Cuxhaven: '库克斯港',
  Germany: '德国',
})

function localizedCanonicalLocation(canonical: string, locale: string): string {
  if (!canonical) return ''
  if (locale.toLowerCase().startsWith('zh')) {
    return ZH_LOCATION_ALIASES[canonical] || canonical
  }
  return canonical
}

export function localizedProfileLocation(
  profile?: PersonProfileProjection | null,
  locale = 'zh-CN',
): string {
  if (!profile) return ''
  const canonical = profile.city || profile.region || profile.country || profile.raw_location || ''
  return localizedCanonicalLocation(canonical, locale)
}

export function localizedProfileCountry(
  profile?: PersonProfileProjection | null,
  locale = 'zh-CN',
): string {
  if (!profile) return ''
  return localizedCanonicalLocation(profile.country || profile.country_code || '', locale)
}

export function profileAgeLabel(
  profile?: PersonProfileProjection | null,
  locale = 'zh-CN',
): string {
  if (profile?.age === undefined || profile?.age === null) return ''
  const age = profile.age
  const precision = profile.age_precision
  if (locale.toLowerCase().startsWith('zh')) {
    if (precision === 'year') return `约${age}岁`
    if (precision === 'observed') return `${age}岁（记录）`
    return `${age}岁`
  }
  if (precision === 'year') return `about ${age}`
  if (precision === 'observed') return `${age} (observed)`
  return String(age)
}

export function personProfileLine(
  profile?: PersonProfileProjection | null,
  locale = 'zh-CN',
): string {
  if (!profile) return ''
  return [
    localizedProfileLocation(profile, locale),
    profileAgeLabel(profile, locale),
    profile.occupation || '',
  ].filter(Boolean).join(' · ')
}

export function personProfileAvatarUrl(profile?: PersonProfileProjection | null): string {
  return profile?.avatar?.url?.trim() || ''
}
