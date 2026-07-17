// Mã ngôn ngữ phổ biến cho generate report (per-command --language).
// Dùng chung cho ingest-spreadsheet, custom-report và trang cài đặt ngôn ngữ mặc định.
export const LANGUAGES = [
  { code: '', label: 'Mặc định (theo cấu hình NotebookLM)' },
  { code: 'vi', label: 'Tiếng Việt (vi)' },
  { code: 'en', label: 'English (en)' },
  { code: 'ja', label: '日本語 (ja)' },
  { code: 'zh_Hans', label: '简体中文 (zh_Hans)' },
  { code: 'ko', label: '한국어 (ko)' },
  { code: 'fr', label: 'Français (fr)' },
]
