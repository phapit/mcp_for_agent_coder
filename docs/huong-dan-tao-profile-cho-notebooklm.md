# Tạo profile mới rồi login vào profile đó

```bash
notebooklm profile create your_profile
notebooklm -p your_profile login
notebooklm -p your_profile auth check --test --json
```

# Nếu muốn dùng profile đó làm mặc định cho các lệnh sau:

```bash
notebooklm profile switch work
```

# Dùng browser cookies để bind tài khoản mới vào profile mới
Phù hợp khi bạn không muốn mở flow login Playwright:
```bash
notebooklm profile create work
notebooklm auth inspect --browser chrome
notebooklm -p work login --browser-cookies 'chrome::Default' --account your-email@gmail.com
notebooklm -p work auth check --test --json
```