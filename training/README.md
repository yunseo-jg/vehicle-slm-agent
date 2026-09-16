# training

8~9주차. 로컬 SLM이 우리 도구 형식을 정확히 뱉게 만드는 곳.

- `synth_data.py` 클라우드 모델로 발화 1,000~2,000건 합성 → 온톨로지로 검증 → 스키마 위반 폐기
- `data/` 학습용 jsonl (합성 결과). 원본 발화는 넣지 않는다
- `lora_colab.ipynb` Unsloth + Colab LoRA 학습 → GGUF 변환 → Ollama 등록
- 가중치(`*.gguf`, `*.safetensors`)는 커밋하지 않는다

학습 데이터 한 건 형식

```json
{"messages": [
  {"role": "user", "content": "히터 좀 세게"},
  {"role": "assistant", "tool_calls": [{"name": "set_hvac_temperature", "arguments": {"zone": "driver", "value": 26}}]}
]}
```
