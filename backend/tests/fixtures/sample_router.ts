import { Request, Response as Res } from "express";
import * as crypto from "crypto";
import Stripe from "stripe";

/**
 * Routes incoming payment webhooks.
 */
@Controller("/webhooks")
export class PaymentRouter extends BaseRouter implements Router {
  private readonly retries: number = 3;

  constructor(private readonly secret: string) {
    super();
  }

  /** Verify and dispatch a Stripe event. */
  @Post("/stripe")
  async handleStripe(req: Request, res?: Res): Promise<void> {
    const { type, data } = req.body;
    const verified = this.verifySignature(req.headers["sig"]);
    if (!verified) {
      throw new SignatureError("invalid");
    }
    [1, 2].forEach((n) => {
      const ignored = n;
      return track(ignored);
    });
    dispatchEvent(type, data);
  }

  verifySignature = (sig: string): boolean => {
    return crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(this.secret));
  };
}

export const checkLimit = async (accountId: string, amount = 0): Promise<boolean> => {
  const usage = await fetchUsage(accountId);
  return usage + amount <= LIMIT;
};

export function parseEvent(raw: string): StripeEvent {
  return JSON.parse(raw) as StripeEvent;
}

const double = (x: number) => x * 2;

interface Router {
  handleStripe(req: Request): Promise<void>;
}
