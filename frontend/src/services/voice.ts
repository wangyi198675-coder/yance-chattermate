/*
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
*/

import api from '@/services/api'

export interface VoiceAttachment {
  id: number
  file_url: string
  filename: string
  content_type: string
  file_size: number
}

export interface GeneratedVoiceAsset {
  attachment: VoiceAttachment
  provider: {
    provider: 'elevenlabs'
    voice_id: string
    model_id: string
    output_format: string
    professional_clone: boolean
    pvc_gate?: Record<string, unknown> | null
  }
  send_authority: string
}

export const voiceService = {
  async generateSpeech(text: string): Promise<GeneratedVoiceAsset> {
    const response = await api.post<GeneratedVoiceAsset>('/voice/tts', {
      text,
      voice_kind: 'standard',
      explicit_voice_owner_consent: false,
    })
    return response.data
  },

  async checkProfessionalClone(
    voiceId: string,
    explicitVoiceOwnerConsent: boolean,
  ): Promise<Record<string, unknown>> {
    const response = await api.post('/voice/pvc/eligibility', {
      voice_id: voiceId,
      explicit_voice_owner_consent: explicitVoiceOwnerConsent,
    })
    return response.data
  },
}
