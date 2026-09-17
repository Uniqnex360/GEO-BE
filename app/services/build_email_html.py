import os
import resend


def _score_color(score: int) -> str:
    """Return a color based on score thresholds (red/amber/green)."""
    if score >= 70:
        return "#16a34a"  # green
    if score >= 45:
        return "#d97706"  # amber
    return "#dc2626"  # red


def _score_bar(label: str, score: int) -> str:
    """Render a single labeled progress bar for a 0-100 score."""
    color = _score_color(score)
    return f"""
    <tr>
        <td style="padding: 8px 0; font-size: 13px; color: #444; width: 140px;">{label}</td>
        <td style="padding: 8px 0;">
            <div style="background:#eef0f5; border-radius: 6px; height: 10px; width: 100%; overflow:hidden;">
                <div style="background:{color}; height: 10px; width: {score}%; border-radius: 6px;"></div>
            </div>
        </td>
        <td style="padding: 8px 0 8px 12px; font-size: 13px; font-weight: 700; color:{color}; width: 40px; text-align:right;">{score}</td>
    </tr>
    """


def build_geo_email(data: dict) -> str:
    product = data["product"]

    actual_content = product.get("actual_content", {}) or {}
    product_content = actual_content.get("product_content", {}) or {}

    # Prefer the real scraped product title/URL over the tenant label.
    product_name = product_content.get("product_title") or product.get(
        "name", "Your Product"
    )
    product_url = actual_content.get("url") or product.get("product_url", "")
    brand_name = product_content.get("brand") or product.get("brand_name", "")
    price = product_content.get("price")
    currency = product_content.get("currency", "")

    chats = product.get("chats", [])
    geo_audits = product.get("geo_audits", []) or []

    total_analyses = len(chats)
    total_queries = sum(len(chat.get("search_queries", [])) for chat in chats)
    total_citations = sum(len(chat.get("citations", [])) for chat in chats)

    # Pull per-category scores from the richest available audit (usually Claude's).
    score_fields = {}
    best_audit = None
    for audit in geo_audits:
        pd_ = (audit.get("audit_data") or {}).get("product_details", {})
        if pd_.get("product_title", {}).get("score", 0):
            best_audit = audit
            break
    if best_audit is None and geo_audits:
        best_audit = geo_audits[0]

    if best_audit:
        pd_ = (best_audit.get("audit_data") or {}).get("product_details", {})
        for key, label in [
            ("product_title", "Title"),
            ("description_analysis", "Description"),
            ("keywords", "Keywords/SEO"),
            ("assets", "Media Assets"),
        ]:
            entry = pd_.get(key)
            if isinstance(entry, dict) and "score" in entry:
                score_fields[label] = entry.get("score", 0)

    overall_score = (
        round(sum(score_fields.values()) / len(score_fields)) if score_fields else None
    )

    # Best share-of-voice query, for a highlight stat.
    best_sov = 0
    for chat in chats:
        for q in chat.get("search_queries", []):
            best_sov = max(best_sov, q.get("share_of_voice", 0) or 0)

    score_bars_html = "".join(
        _score_bar(label, score) for label, score in score_fields.items()
    )

    overall_block = ""
    if overall_score is not None:
        color = _score_color(overall_score)
        overall_block = f"""
        <div style="text-align:center; margin: 4px 0 28px;">
            <div style="
                display:inline-flex; align-items:center; justify-content:center;
                width:120px; height:120px; border-radius:50%;
                background:conic-gradient({color} {overall_score * 3.6}deg, #eef0f5 0deg);
                position:relative;
            ">
                <div style="
                    width:96px; height:96px; border-radius:50%; background:#ffffff;
                    display:flex; align-items:center; justify-content:center;
                    flex-direction:column;
                ">
                    <span style="font-size:28px; font-weight:800; color:{color};">{overall_score}</span>
                    <span style="font-size:10px; color:#888; letter-spacing:0.5px;">GEO SCORE</span>
                </div>
            </div>
        </div>
        """

    # Per-AI-engine cards
    model_cards_html = ""
    model_colors = {
        "GPT": "#10a37f",
        "CLAUDE": "#d97757",
        "GEMINI": "#4285f4",
    }
    for chat in chats:
        model = chat.get("model_choice", "AI Engine")
        queries = chat.get("search_queries", [])
        citations = chat.get("citations", [])
        color = model_colors.get(model, "#6d5dfc")
        found = sum(1 for q in queries if q.get("product_found"))

        model_cards_html += f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #eef0f5; border-radius:10px; margin-bottom:12px;">
            <tr>
                <td style="padding:16px 18px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td>
                                <span style="
                                    display:inline-block; width:8px; height:8px; border-radius:50%;
                                    background:{color}; margin-right:8px;
                                "></span>
                                <span style="font-size:15px; font-weight:700; color:#222;">{model}</span>
                            </td>
                            <td style="text-align:right; font-size:12px; color:#888;">
                                {found}/{len(queries)} queries found your product
                            </td>
                        </tr>
                    </table>
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;">
                        <tr>
                            <td style="text-align:center; padding:6px; border-right:1px solid #f0f0f4;">
                                <div style="font-size:18px; font-weight:700; color:#222;">{len(queries)}</div>
                                <div style="font-size:11px; color:#888;">Queries</div>
                            </td>
                            <td style="text-align:center; padding:6px;">
                                <div style="font-size:18px; font-weight:700; color:#222;">{len(citations)}</div>
                                <div style="font-size:11px; color:#888;">Citations</div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
        """

    price_line = f"{currency} {price}" if price else ""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Your GEO Audit is Complete</title>
    </head>
    <body style="margin:0; padding:0; background:#f2f3f7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; color:#222;">

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f3f7; padding: 24px 0;">
        <tr>
            <td align="center">
                <table role="presentation" width="640" cellpadding="0" cellspacing="0"
                       style="background:#ffffff; border-radius:14px; overflow:hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06);">

                    <!-- Header -->
                    <tr>
                        <td style="background:linear-gradient(135deg,#6d5dfc,#8b7bff); padding:36px 32px;">
                            <div style="font-size:12px; letter-spacing:1.5px; color:#e4e0ff; text-transform:uppercase; font-weight:600;">
                                GEO Audit Report
                            </div>
                            <div style="font-size:26px; font-weight:800; color:#ffffff; margin-top:8px;">
                                Your AI Visibility Audit is Ready
                            </div>
                            <div style="font-size:14px; color:#e9e6ff; margin-top:6px;">
                                See how {brand_name or "your brand"} shows up across AI search engines
                            </div>
                        </td>
                    </tr>

                    <!-- Body -->
                    <tr>
                        <td style="padding:32px;">

                            <div style="font-size:12px; color:#888; text-transform:uppercase; letter-spacing:0.5px; font-weight:700;">
                                Product
                            </div>
                            <div style="font-size:19px; font-weight:700; color:#222; margin-top:4px;">
                                {product_name}
                            </div>
                            {f'<div style="font-size:13px; color:#888; margin-top:2px;">{price_line}</div>' if price_line else ""}

                            {overall_block}

                            <!-- Top-line metrics -->
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 8px 0 28px;">
                                <tr>
                                    <td width="33%" style="text-align:center; padding:16px 6px; background:#f7f7fb; border-radius:10px 0 0 10px;">
                                        <div style="font-size:24px; font-weight:800; color:#6d5dfc;">{total_analyses}</div>
                                        <div style="font-size:11px; color:#888; margin-top:4px;">AI Engines Checked</div>
                                    </td>
                                    <td width="2" style="background:#ffffff;"></td>
                                    <td width="33%" style="text-align:center; padding:16px 6px; background:#f7f7fb;">
                                        <div style="font-size:24px; font-weight:800; color:#6d5dfc;">{total_queries}</div>
                                        <div style="font-size:11px; color:#888; margin-top:4px;">Queries Run</div>
                                    </td>
                                    <td width="2" style="background:#ffffff;"></td>
                                    <td width="33%" style="text-align:center; padding:16px 6px; background:#f7f7fb; border-radius:0 10px 10px 0;">
                                        <div style="font-size:24px; font-weight:800; color:#6d5dfc;">{total_citations}</div>
                                        <div style="font-size:11px; color:#888; margin-top:4px;">Citations Found</div>
                                    </td>
                                </tr>
                            </table>

                            {f'''
                            <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:14px 18px; margin-bottom:28px;">
                                <span style="font-size:13px; color:#15803d; font-weight:600;">
                                    Peak share of voice: {best_sov:.1f}%
                                </span>
                                <span style="font-size:12px; color:#4b7a5e;"> — your best-performing query result</span>
                            </div>
                            ''' if best_sov else ""}

                            <!-- Score breakdown -->
                            {"<div style='font-size:15px; font-weight:700; margin-bottom:12px;'>Score Breakdown</div>" if score_bars_html else ""}
                            {f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">{score_bars_html}</table>' if score_bars_html else ""}

                            <!-- Per-engine breakdown -->
                            <div style="font-size:15px; font-weight:700; margin-bottom:12px;">AI Engine Analysis</div>
                            {model_cards_html}

                            <!-- What we analyzed -->
                            <div style="font-size:15px; font-weight:700; margin: 24px 0 12px;">What We Analyzed</div>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                                <tr><td style="padding:5px 0; font-size:14px; color:#444;">✓ Product visibility across AI search engines</td></tr>
                                <tr><td style="padding:5px 0; font-size:14px; color:#444;">✓ Search queries related to your product</td></tr>
                                <tr><td style="padding:5px 0; font-size:14px; color:#444;">✓ Competitor mentions and citations</td></tr>
                                <tr><td style="padding:5px 0; font-size:14px; color:#444;">✓ Optimization opportunities</td></tr>
                            </table>

                            {f'''
                            <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:28px;">
                                <tr>
                                    <td style="background:#6d5dfc; border-radius:8px;">
                                        <a href="{product_url}" style="display:inline-block; padding:13px 24px; font-size:14px; font-weight:700; color:#ffffff; text-decoration:none;">
                                            View Full Report
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            ''' if product_url else ""}

                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding:20px 32px; background:#f7f7f9; text-align:center;">
                            <div style="font-size:12px; color:#999;">
                                GEO Audit Report &middot; This email was automatically generated.
                            </div>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>

    </body>
    </html>
    """

    return html
