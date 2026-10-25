"""Customer and internal notifications."""

import smtplib
from email.message import EmailMessage
from string import Template

import requests

SLACK_WEBHOOK_URL = "https://hooks.slack.example/services/T000/B000"


class EmailTemplate:
    """A `$placeholder` email template with subject and body."""

    def __init__(self, subject: str, body: str):
        self.subject = Template(subject)
        self.body = Template(body)

    def render(self, **context) -> tuple[str, str]:
        return self.subject.substitute(context), self.body.substitute(context)


RECEIPT = EmailTemplate("Your receipt for $amount", "Hi $name, we received your payment of $amount. Thanks!")


def send_receipt_email(customer: dict, payment: dict) -> None:
    """Email the customer a receipt for a successful payment."""
    subject, body = RECEIPT.render(name=customer["name"], amount=f"${payment['amount'] / 100:.2f}")
    message = EmailMessage()
    message["To"], message["Subject"] = customer["email"], subject
    message.set_content(body)
    with smtplib.SMTP("localhost") as smtp:
        smtp.send_message(message)


def notify_slack(channel: str, text: str) -> None:
    """Post a message to an internal Slack channel."""
    requests.post(SLACK_WEBHOOK_URL, json={"channel": channel, "text": text}, timeout=5)
