# FROZEN_UI_CAPABILITY_WIRING_REPORT

Frozen Primary + Secondary layout remains unchanged. Phase 3 added **no visible button, page, panel, label, or CSS redesign**.

Existing controls now emit additional invisible `capability-route` metadata while retaining their original semantic events:

| Existing Frozen control | Owner route metadata | Mature owner |
|---|---|---|
| 联系人 | `girlfriend/find_contact` | ChatterMate Customer/People |
| 模型/推理 | `girlfriend/model_selection` | ChatterMate AIConfig/model catalog |
| 回复建议 (on open) | `reply/candidate_generation` | ChatterMate Agent/model runtime |
| `+` attachment | `reply/file_attachment` | ChatterMate FileAttachment/file services |
| 发送并学习 | `reply/final_send` | ChatterMate message_delivery + ChannelAdapter |

The frontend contains only a typed static map (`capabilityWiring.ts`). It does not execute backend actions, create an event bus, or own business state. Translation/Relationship/Voice/Generative Media remain unavailable until their external owners pass production admission.
