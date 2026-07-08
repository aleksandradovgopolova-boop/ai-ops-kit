# Reports Specification

## Purpose
Просмотр и выгрузка отчётов для аутентифицированных пользователей: отображение
содержимого отчёта и экспорт данных во внешние форматы для последующего анализа.

## Requirements

### Requirement: Report viewing
The system SHALL display a report to an authenticated user.

#### Scenario: View a report
- GIVEN an authenticated user
- WHEN the user opens a report
- THEN the report content is displayed
