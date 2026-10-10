import { describe, expect, it } from 'vitest'
import {
  localizedProfileCountry,
  localizedProfileLocation,
  personProfileAvatarUrl,
  personProfileLine,
  profileAgeLabel,
} from '@/utils/personProfile'
import type { PersonProfileProjection } from '@/types/people'

describe('person profile display projection', () => {
  it('localizes known cities without mutating canonical values', () => {
    const profile: PersonProfileProjection = { city: 'Cuxhaven', country: 'Germany' }
    expect(localizedProfileLocation(profile, 'zh-CN')).toBe('库克斯港')
    expect(localizedProfileCountry(profile, 'zh-CN')).toBe('德国')
    expect(profile.city).toBe('Cuxhaven')
    expect(profile.country).toBe('Germany')
  })

  it('makes birth-year precision visible rather than pretending an exact age', () => {
    const profile: PersonProfileProjection = { age: 43, age_precision: 'year' }
    expect(profileAgeLabel(profile, 'zh-CN')).toBe('约43岁')
  })

  it('marks observed age as an observation in display', () => {
    const profile: PersonProfileProjection = { age: 43, age_precision: 'observed' }
    expect(profileAgeLabel(profile, 'zh-CN')).toBe('43岁（记录）')
  })

  it('builds the weak city age occupation line from bounded fields only', () => {
    const profile: PersonProfileProjection = {
      city: 'Berlin',
      age: 43,
      age_precision: 'exact',
      occupation: 'Designer',
    }
    expect(personProfileLine(profile, 'zh-CN')).toBe('柏林 · 43岁 · Designer')
  })

  it('handles missing profile and avatar safely', () => {
    expect(personProfileLine(null, 'zh-CN')).toBe('')
    expect(personProfileAvatarUrl(undefined)).toBe('')
    expect(personProfileAvatarUrl({ avatar: { url: ' https://example.test/a.jpg ' } })).toBe(
      'https://example.test/a.jpg',
    )
  })
})
