"""Invoice generation, tax and discounts."""

from dataclasses import dataclass, field

from .storage import PaymentRepository

TAX_RATES = {"US-CA": 0.0725, "US-NY": 0.04, "EU-DE": 0.19, "EU-FR": 0.20}


@dataclass
class Invoice:
    account_id: str
    period: str
    lines: list[dict] = field(default_factory=list)
    total: int = 0


def compute_tax(subtotal: int, region: str) -> int:
    """Sales tax / VAT owed on a subtotal for the customer's region, rounded to cents."""
    return round(subtotal * TAX_RATES.get(region, 0.0))


def apply_discount(subtotal: int, coupon: dict | None) -> int:
    """Apply a percent-off or fixed-amount coupon, never going below zero."""
    if not coupon:
        return subtotal
    if coupon["kind"] == "percent":
        return round(subtotal * (1 - coupon["value"] / 100))
    return max(0, subtotal - coupon["value"])


def generate_invoice(account_id: str, period: str, region: str, coupon: dict | None = None) -> Invoice:
    """Build the monthly invoice from the account's payments, applying discounts and tax."""
    payments = PaymentRepository().list_by_customer(account_id)
    lines = [{"description": p["id"], "amount": p["amount"]} for p in payments if p["status"] == "succeeded"]
    subtotal = apply_discount(sum(line["amount"] for line in lines), coupon)
    return Invoice(account_id, period, lines, subtotal + compute_tax(subtotal, region))


def render_invoice_pdf(invoice: Invoice, path: str) -> str:
    """Write the invoice to a PDF file and return its path."""
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(path)
    y = 800
    for line in invoice.lines:
        pdf.drawString(72, y, f"{line['description']}: {line['amount'] / 100:.2f}")
        y -= 18
    pdf.drawString(72, y - 18, f"Total: {invoice.total / 100:.2f}")
    pdf.save()
    return path
