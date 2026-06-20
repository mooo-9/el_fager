"""
Printer tools for El Fager.

List printers, print files and text. Uses win32print/win32api from pywin32
(already installed as a dependency of pygetwindow).
"""


def list_printers() -> str:
    """List all installed printers and which one is the default."""
    try:
        import win32print
        default = win32print.GetDefaultPrinter()
        printers = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
            None, 2
        )
        if not printers:
            return "No printers installed."
        lines = ["Available printers:"]
        for p in printers:
            name = p["pPrinterName"]
            marker = " [default]" if name == default else ""
            lines.append(f"  - {name}{marker}")
        return "\n".join(lines)
    except Exception as e:
        return f"[list_printers failed: {e}]"


def get_default_printer() -> str:
    """Return the name of the current default printer."""
    try:
        import win32print
        default = win32print.GetDefaultPrinter()
        return f"Default printer: {default}"
    except Exception as e:
        return f"[get_default_printer failed: {e}]"


def set_default_printer(name: str) -> str:
    """Set a printer as the Windows default."""
    try:
        import win32print
        # Verify it exists
        printers = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
            None, 2
        )
        names = [p["pPrinterName"] for p in printers]
        name_lower = name.lower()
        match = next((n for n in names if name_lower in n.lower()), None)
        if not match:
            return f"[Printer '{name}' not found. Available: {', '.join(names)}]"
        win32print.SetDefaultPrinter(match)
        return f"Default printer set to: {match}"
    except Exception as e:
        return f"[set_default_printer failed: {e}]"


def print_file(path: str, printer: str = None) -> str:
    """Send a file to a printer using Windows ShellExecute print verb."""
    try:
        import os
        import win32api
        import win32print

        if not os.path.exists(path):
            return f"[print_file failed: file not found: {path}]"

        if printer:
            # Temporarily set as default if a specific printer is requested
            old_default = win32print.GetDefaultPrinter()
            win32print.SetDefaultPrinter(printer)
        else:
            old_default = None

        try:
            win32api.ShellExecute(0, "print", path, None, ".", 0)
            printer_used = printer or win32print.GetDefaultPrinter()
            return f"Sent to printer: {printer_used}\nFile: {path}"
        finally:
            if old_default and printer:
                win32print.SetDefaultPrinter(old_default)

    except Exception as e:
        return f"[print_file failed: {e}]"


def print_text(text: str, title: str = "El Fager", printer: str = None) -> str:
    """Print plain text by creating a temporary PDF and sending it to the printer."""
    try:
        import tempfile
        import os
        from tools.pdf_tool import create_pdf

        # Write to a temp PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="elfager_print_") as f:
            tmp_path = f.name

        result = create_pdf(text, tmp_path, title=title)
        if "[" in result and "failed" in result:
            os.unlink(tmp_path)
            return f"[print_text failed during PDF creation: {result}]"

        print_result = print_file(tmp_path, printer=printer)

        # Clean up temp file after a short delay (printer spools it)
        import threading, time
        def _cleanup():
            time.sleep(10)
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        threading.Thread(target=_cleanup, daemon=True).start()

        return f"Print sent ({len(text)} chars, title: '{title}').\n{print_result}"
    except Exception as e:
        return f"[print_text failed: {e}]"
