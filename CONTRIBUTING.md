# Contributing to CarbonWise

Thank you for your interest in contributing to the CarbonWise Carbon Footprint Awareness Platform! This document provides guidelines and instructions to help you get started.

---

## 📋 Code of Conduct

This project follows a respectful and inclusive code of conduct. Please be courteous in all interactions.

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.9+** installed on your system.
- **Git** for version control.

### Local Development Setup

```bash
# 1. Clone the repository
git clone https://github.com/VinayVerma325/Carbon-Footprint-Awareness-Platform.git
cd Carbon-Footprint-Awareness-Platform

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
.venv\Scripts\activate      # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and configure environment variables
cp .env.example .env  # or create .env manually

# 5. Run the development server
python main.py

# 6. Run the test suite
python -m pytest tests/ -v
```

---

## 🏗️ Project Structure

```
├── main.py                  # FastAPI server + routes
├── config.py                # Environment configuration
├── exceptions.py            # Custom exception hierarchy
├── sanitizer.py             # Input sanitization utilities
├── core/
│   ├── __init__.py
│   └── calculator.py        # CO₂ calculation engine
├── services/
│   ├── __init__.py
│   └── google_services.py   # Google Routes API + Firestore
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared test fixtures
│   └── test_platform.py     # Full test suite
├── index.html               # Frontend dashboard
├── app.js                   # Client-side logic
└── style.css                # Stylesheet
```

---

## 📏 Coding Standards

### Python (Backend)

- **Type Annotations**: All functions must include full type hints.
- **Docstrings**: Use Google-style or Sphinx-style docstrings for every public class, method, and function.
- **Custom Exceptions**: Use exceptions from `exceptions.py` instead of bare `ValueError` / `Exception`.
- **Logging**: Use structured logging (`logger.warning("msg: %s", val)`) — never f-strings in log calls.
- **Security**: Never hardcode API keys or secrets. All credentials come from environment variables.

### JavaScript (Frontend)

- **DOM Safety**: Use `textContent`, `createElement`, and `appendChild` — never `innerHTML` for dynamic content.
- **Accessibility**: All interactive elements must have ARIA labels. Use `aria-live` regions for dynamic updates.

### CSS

- Use CSS custom properties (variables) for theming.
- Support dark mode, light mode, and glass theme.

---

## ✅ Testing Requirements

- All new features **must** include corresponding unit tests.
- Tests must pass before any pull request is merged.
- Target test coverage: **≥ 90%**.

Run the test suite:
```bash
python -m pytest tests/ -v
```

---

## 🔒 Security Guidelines

1. **Never commit secrets** — API keys, service account files, and `.env` must stay in `.gitignore`.
2. **Input validation** — All user inputs must be validated with Pydantic models and sanitized with `sanitizer.py`.
3. **HTTP headers** — The security middleware in `main.py` must not be weakened without security review.

---

## 📬 Submitting Changes

1. Fork the repository and create a feature branch from `main`.
2. Make your changes following the coding standards above.
3. Add or update tests as needed.
4. Run the full test suite and ensure all tests pass.
5. Submit a pull request with a clear description of your changes.

---

## 🐛 Reporting Issues

Please open a GitHub issue with:
- A clear, descriptive title.
- Steps to reproduce the problem.
- Expected vs. actual behavior.
- Environment details (OS, Python version, browser).

---

Thank you for helping make CarbonWise better! 🌍
