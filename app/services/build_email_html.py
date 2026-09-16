import os
import resend


def build_geo_email(data: dict) -> str:
    product = data["product"]

    product_name = product.get("name", "Your Product")
    product_url = product.get("product_url", "")

    chats = product.get("chats", [])

    total_analyses = len(chats)
    total_queries = sum(len(chat.get("search_queries", [])) for chat in chats)
    total_citations = sum(len(chat.get("citations", [])) for chat in chats)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                margin: 0;
                padding: 0;
                background: #f5f5f7;
                font-family: Arial, sans-serif;
                color: #222;
            }}

            .container {{
                max-width: 700px;
                margin: 30px auto;
                background: white;
                border-radius: 12px;
                overflow: hidden;
            }}

            .header {{
                background: #6d5dfc;
                color: white;
                padding: 30px;
            }}

            .header h1 {{
                margin: 0 0 8px;
                font-size: 26px;
            }}

            .content {{
                padding: 30px;
            }}

            .stats {{
                display: flex;
                gap: 12px;
                margin: 25px 0;
            }}

            .stat {{
                flex: 1;
                background: #f7f7fb;
                padding: 18px;
                text-align: center;
                border-radius: 8px;
            }}

            .stat-number {{
                font-size: 24px;
                font-weight: bold;
            }}

            .stat-label {{
                color: #777;
                font-size: 13px;
                margin-top: 5px;
            }}

            .section {{
                margin-top: 30px;
            }}

            .section h2 {{
                font-size: 18px;
                margin-bottom: 12px;
            }}

            .model {{
                border: 1px solid #eee;
                border-radius: 8px;
                padding: 16px;
                margin-bottom: 12px;
            }}

            .model-name {{
                font-weight: bold;
                font-size: 16px;
            }}

            .button {{
                display: inline-block;
                margin-top: 25px;
                padding: 12px 20px;
                background: #6d5dfc;
                color: white !important;
                text-decoration: none;
                border-radius: 6px;
            }}

            .footer {{
                padding: 20px 30px;
                background: #f7f7f7;
                color: #888;
                font-size: 12px;
                text-align: center;
            }}
        </style>
    </head>

    <body>

        <div class="container">

            <div class="header">
                <h1>Your GEO Audit is Complete</h1>
                <div>AI visibility analysis for your product</div>
            </div>

            <div class="content">

                <h2>{product_name}</h2>

                <p>
                    We've completed your GEO audit and analyzed how your
                    product appears across AI search engines.
                </p>

                <div class="stats">

                    <div class="stat">
                        <div class="stat-number">{total_analyses}</div>
                        <div class="stat-label">AI Analyses</div>
                    </div>

                    <div class="stat">
                        <div class="stat-number">{total_queries}</div>
                        <div class="stat-label">Queries</div>
                    </div>

                    <div class="stat">
                        <div class="stat-number">{total_citations}</div>
                        <div class="stat-label">Citations</div>
                    </div>

                </div>

                <div class="section">
                    <h2>AI Engine Analysis</h2>
        """

    for chat in chats:
        model = chat.get("model_choice", "AI Engine")
        queries = chat.get("search_queries", [])

        html += f"""
                    <div class="model">
                        <div class="model-name">{model}</div>
                        <p>
                            {len(queries)} search queries were analyzed.
                        </p>
                    </div>
                """

    html += f"""
                </div>

                <div class="section">
                    <h2>What We Analyzed</h2>

                    <p>
                        • Product visibility across AI search engines
                    </p>

                    <p>
                        • Search queries related to your product
                    </p>

                    <p>
                        • Competitor mentions and citations
                    </p>

                    <p>
                        • Optimization opportunities
                    </p>
                </div>

                {"<a class='button' href='" + product_url + "'>View Product</a>" if product_url else ""}

            </div>

            <div class="footer">
                GEO Audit Report<br>
                This email was automatically generated.
            </div>

        </div>

    </body>
    </html>
    """

    return html


def send_geo_email(to_email: str, html: str):
    resend.api_key = os.getenv("RESEND_API_KEY")

    response = resend.Emails.send(
        
    )

    return response
