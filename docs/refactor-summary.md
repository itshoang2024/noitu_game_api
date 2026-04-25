# Refactor Summary

## Purpose
Tài liệu này ghi lại các module đã được refactor trong đợt dọn code gần nhất, mô tả thay đổi chính và lý do thực hiện. Phạm vi refactor tập trung vào việc giữ nguyên hành vi hiện có, làm rõ trách nhiệm module, giảm parsing thủ công, giảm lặp code và cải thiện khả năng kiểm thử.

## Verification
Sau refactor đã chạy:

- `conda run -n intro2ai python -m compileall app tests`
- `conda run -n intro2ai python -m pytest -q`

Kết quả kiểm thử gần nhất: `6 passed`.

## Refactored Modules

### `main.py`
**Đã refactor**
- Tách phần tạo FastAPI app vào `create_app()`.
- Đưa import `os` và `WordEvaluator` lên đầu file thay vì import trong startup hook.
- Gom cấu hình CORS và router registration vào một nơi rõ ràng.
- Giữ startup/shutdown hooks nhưng làm luồng khởi tạo tuần tự hơn: tạo bảng DB, tạo thư mục `data`, khởi tạo dictionary, rồi warm up AI service.

**Lý do**
- Giảm side effect rải rác trong file entrypoint.
- Dễ test hoặc tái sử dụng app factory hơn.
- Làm rõ boundary giữa cấu hình app và lifecycle runtime.

### `app/config.py`
**Đã refactor**
- Thêm validator `parse_debug_value()` cho `DEBUG`.
- Cho phép các giá trị môi trường như `release`, `production`, `prod`, `debug`, `development`.

**Lý do**
- Tránh lỗi Pydantic validation khi môi trường đặt `DEBUG=release`.
- Giúp config chịu lỗi tốt hơn mà không cần đổi `.env` ngay lập tức.

### `app/models/schemas.py`
**Đã refactor**
- Bổ sung request schemas:
  - `WordValidationRequest`
  - `WordMeaningRequest`
  - `DictionaryWordRequest`
  - `ThemeWordsUpdateRequest`
  - `WordPairRequest`
  - `StartingWordRequest`
- Dùng default an toàn cho các field có thể trống để giữ behavior cũ của endpoints.

**Lý do**
- Tuân thủ rule của repo: route mới hoặc route sửa không bypass validation bằng JSON parsing thủ công.
- Gom contract request về một nơi, giúp downstream clients và tests dễ theo dõi hơn.

### `app/api/routes/core.py`
**Đã refactor**
- Endpoint `/ask` nhận `WordRequest` thay vì đọc `Request` rồi gọi `await req.json()`.
- Giữ nguyên helper validation/generation hiện có và chỉ đổi cách lấy input.

**Lý do**
- Giảm parsing thủ công ở tầng route.
- Dựa vào Pydantic để chuẩn hóa input, tránh lỗi runtime do payload thiếu key.

### `app/api/routes/game.py`
**Đã refactor**
- Endpoint `/game/check_pair` dùng `WordPairRequest`.
- Endpoint `/game/new_word` dùng `StartingWordRequest`.
- Thêm `_extract_starting_word_request()` để normalize `session_id` và `theme`.
- Giữ helper chọn từ theo theme, scoring và đăng ký từ trong session.

**Lý do**
- Làm rõ request contract cho các endpoint game.
- Giảm lặp normalize `theme` và `session_id`.
- Giữ tương thích với test gọi trực tiếp service function.

### `app/api/routes/word.py`
**Đã refactor**
- Thay `req.json()` bằng `WordValidationRequest` và `WordMeaningRequest`.
- Làm rõ luồng lỗi cho `/word/explain` và `/word/check_meaning`.
- Giữ các response keys hiện có như `structure_valid`, `in_dictionary`, `quality_score`, `final_result`.

**Lý do**
- Tách validation input khỏi business logic.
- Tránh route nuốt nhầm `HTTPException` rồi biến lỗi client thành lỗi 500.
- Code ngắn hơn, dễ đọc theo từng endpoint.

### `app/api/routes/dictionary.py`
**Đã refactor**
- Thay request parsing thủ công bằng `DictionaryWordRequest` và `ThemeWordsUpdateRequest`.
- Thêm `_normalize_words()` để lọc danh sách từ theo theme.
- Dùng `BackgroundTasks` đúng dependency injection thay vì tạo `BackgroundTasks()` thủ công trong route.
- Giữ cơ chế invalidate `quality_scores` sau khi thêm từ vào dictionary.

**Lý do**
- Làm rõ contract của `/dictionary/add` và `/dictionary/update_theme_words`.
- Background task do FastAPI quản lý sẽ đúng lifecycle request hơn.
- Tách phần normalize danh sách từ ra khỏi endpoint để dễ đọc và dễ test.

### `app/api/routes/system.py`
**Đã refactor**
- Tách logic phân phối quality score vào `_build_quality_distribution()`.
- Endpoint `/system/quality_stats` dùng `quality_tracker.get_summary_stats()`.
- Chuẩn hóa response construction cho status, cache, reset và performance.

**Lý do**
- Giảm độ dài endpoint `/performance`.
- Sửa lỗi runtime tiềm ẩn do `QualityTracker` trước đó chưa có `get_summary_stats()`.
- Giữ route system tập trung vào điều phối response, không chứa nhiều logic thống kê inline.

### `app/api/routes/database.py`
**Đã refactor**
- Thêm helper `_count_rows()` để gom logic đếm records.
- Giảm lặp query trong `/database/stats`.
- Dọn imports và dùng `Optional[bool]` cho filter `is_common`.

**Lý do**
- Tránh lặp 5 query count gần giống nhau.
- Làm endpoint stats dễ mở rộng nếu sau này thêm bảng mới.
- Giữ response shape hiện có cho clients.

### `app/api/middleware.py`
**Đã refactor**
- Tách cleanup timestamp cũ vào `_prune_old_timestamps()`.
- Dùng `setdefault()` cho request timestamp theo client IP.
- Giảm nesting trong `RateLimitingMiddleware.dispatch()`.

**Lý do**
- Làm rõ hai trách nhiệm riêng: prune window cũ và kiểm tra rate limit hiện tại.
- Tránh tính lại số request trong 60 giây sau khi timestamp list đã được prune.

### `app/services/ai_service.py`
**Đã refactor**
- Xóa imports không dùng như `json`, `os`, `QUALITY_METRICS_PATH`, `get_db`.
- Thêm `QualityTracker.get_summary_stats()`.
- `generate_high_quality_response()` truyền tiếp `session_id` và `game_service` xuống `generate_response()`.

**Lý do**
- Sửa endpoint `/system/quality_stats`.
- Cho prompt generation có đủ context session để tránh tái dùng từ xung đột trong game.
- Giảm nhiễu import và làm phụ thuộc module rõ hơn.

### `app/services/game_service.py`
**Đã refactor**
- Dùng `collections.Counter` trong `analyze_player_words()`.
- Giảm vòng lặp đếm word và syllable thủ công.

**Lý do**
- Code ngắn hơn nhưng giữ nguyên output: `total_words`, `unique_words`, `top_words`, `top_syllables`.
- Dễ đọc hơn khi thống kê words/syllables.

### `app/database/crud.py`
**Đã refactor**
- Thêm `_normalize_word()` dùng chung.
- Áp dụng normalize cho create/get word, query first/last syllable và kiểm tra word đã dùng trong game.
- Thay boolean comparison kiểu `== True` bằng `.is_(True)`.
- Xóa imports không dùng.

**Lý do**
- Tránh lặp `word.lower().strip()` ở nhiều query.
- Query boolean rõ nghĩa hơn theo SQLAlchemy.
- Giảm rủi ro lệch normalize giữa cache và database.

### `app/utils/validators.py`
**Đã refactor**
- Đưa `normalize` lên import cấp module.
- Đơn giản hóa `validate_vietnamese_syllable()` bằng `normalized.isalpha()`.
- Giữ rule chính: word phải có ít nhất 2 âm tiết và chain phải nối âm tiết cuối/đầu.

**Lý do**
- Loại bỏ chuỗi ký tự tiếng Việt thủ công dài và khó bảo trì.
- Giữ validator đơn giản, permissive đúng với vai trò "likely valid Vietnamese syllable".

### `app/utils/word_evaluator.py`
**Đã refactor**
- Import `validate_word_structure` ở đầu file thay vì import trong function.
- Dùng `setdefault()` khi build `word_chains`.
- Dọn type import order và một phần guard-return trong score reason.

**Lý do**
- Giảm import động trong hot path đánh giá từ.
- Làm logic build chain ngắn hơn, ít nhánh hơn.
- Giữ nguyên cách tính điểm và cache score.

### `tests/test_game_service_session.py`
**Đã refactor**
- Bổ sung entrypoint `if __name__ == "__main__": pytest.main(["-xvs", __file__])`.

**Lý do**
- Cho phép chạy riêng file test này trực tiếp khi debug session cache/database hydration.
- Không ảnh hưởng pytest discovery.

## Non-Functional Notes
- Không có thay đổi database schema trong `app/database/models.py`, nên không cần Alembic migration cho đợt refactor này.
- Các endpoint chính vẫn giữ path và response keys hiện có.
- Một số file được rewrite bằng nội dung UTF-8 rõ ràng hơn; Git trên Windows có cảnh báo LF sẽ được thay bằng CRLF khi touch file lần sau.

## Suggested Review Checklist
- Kiểm tra lại các route đã đổi sang Pydantic request model có còn khớp frontend/game client không.
- Chạy `conda run -n intro2ai python -m pytest -q`.
- Nếu có live Gemini key, chạy thêm test live riêng biệt trước khi deploy.
- Smoke test các endpoint: `/ask`, `/game/new_word`, `/word/validate`, `/dictionary/add`, `/system/quality_stats`.
