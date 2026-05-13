# Notes

_(заметок по ходу пока не было)_

## 2026-05-13T14:45:54Z

Turn 2: scalpel ПРАВИЛЬНО диагностировал баг (отсутствие _write в mark_done), но при write_file сгенерировал полный файл с битыми отступами — def методы оказались вне класса, удалены docstring'и, @dataclass декоратор у Todo. Тесты теперь падают на другом — ImportError / AttributeError. Это про известную проблему: 14b на write_file целиком теряет вертикальную структуру. Smell: write_file для большого файла без range/insert — рискованно. Возможное лечение: научить write_file mode чтобы scalpel предпочитал range_replace для одной функции; либо post-write валидация через py_compile.
