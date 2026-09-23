from io import BytesIO

import requests
from fpdf import FPDF
from fpdf.enums import MethodReturnValue

# ============================================================
# GET BEST RECOMMENDATION
# ============================================================


def clean_pdf_text(text):
    if text is None:
        return ""

    return (
        str(text)
        .replace("–", "-")
        .replace("—", "-")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("…", "...")
        .replace("✓", "[OK]")
        .replace("→", "->")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


def get_best_recommendation(
    product_data: dict,
    criterion: str,
):
    """
    Get the highest-impact recommendation for a criterion.
    """

    models = product_data.get(
        "recommandation_v2",
        {},
    ).get(
        "models",
        [],
    )

    recommendations = []

    for model in models:

        data = model.get(
            criterion,
            {},
        )

        for recommendation in data.get(
            "recommendations",
            [],
        ):

            recommendations.append(recommendation)

    if not recommendations:
        return None

    recommendations.sort(
        key=lambda x: x.get("impact", 0),
        reverse=True,
    )

    return recommendations[0]


# ============================================================
# STATUS
# ============================================================


def get_status(score):
    if score >= 70:
        return "Strong"
    elif score >= 45:
        return "Needs Improvement"
    else:
        return "Needs Improvement"


def get_priority(score):
    if score < 45:
        return "HIGH"
    elif score < 70:
        return "MEDIUM"
    else:
        return "LOW"


# ============================================================
# SCORE HELPERS
# ============================================================


def get_scores(product_data: dict):
    """
    Calculate all report scores from the actual API JSON.

    Returns:
        scores, overall

    scores contains:
        title
        description
        attributes
        features
        assets
        pricing
        ai_visibility
        product_readiness
        recommendation_readiness
    """

    recommandation_v2 = product_data.get(
        "recommandation_v2",
        {},
    )

    criteria = recommandation_v2.get(
        "criteria",
        {},
    )

    models = recommandation_v2.get(
        "models",
        [],
    )

    # --------------------------------------------------------
    # Criterion scores
    # --------------------------------------------------------

    title = criteria.get(
        "title",
        {},
    ).get(
        "score",
        0,
    )

    assets = criteria.get(
        "assets",
        {},
    ).get(
        "score",
        0,
    )

    pricing = criteria.get(
        "pricing",
        {},
    ).get(
        "score",
        0,
    )

    features = criteria.get(
        "features",
        {},
    ).get(
        "score",
        0,
    )

    attributes = criteria.get(
        "attributes",
        {},
    ).get(
        "score",
        0,
    )

    description = criteria.get(
        "description",
        {},
    ).get(
        "score",
        0,
    )

    scores = {
        "title": title,
        "description": description,
        "attributes": attributes,
        "features": features,
        "assets": assets,
        "pricing": pricing,
    }

    # --------------------------------------------------------
    # Product Readiness
    #
    # Average of the 6 actual product criteria.
    # --------------------------------------------------------

    product_readiness = round(
        (title + description + attributes + features + assets + pricing) / 6
    )

    # --------------------------------------------------------
    # AI Visibility
    #
    # Each model has its own scores.
    # Calculate each model's average, then average
    # the model scores.
    # --------------------------------------------------------

    model_scores = []

    for model in models:

        model_total = 0
        model_count = 0

        for criterion in [
            "title",
            "assets",
            "pricing",
            "features",
            "attributes",
            "description",
        ]:

            criterion_data = model.get(
                criterion,
                {},
            )

            score = criterion_data.get("score")

            if score is not None:
                model_total += score
                model_count += 1

        if model_count:
            model_scores.append(model_total / model_count)

    if model_scores:

        ai_visibility = round(sum(model_scores) / len(model_scores))

    else:
        ai_visibility = 0

    # --------------------------------------------------------
    # Recommendation Readiness
    #
    # avg_impact is 0-10.
    # Convert it to a percentage.
    # --------------------------------------------------------

    impact_scores = []

    for criterion in [
        "title",
        "assets",
        "pricing",
        "features",
        "attributes",
        "description",
    ]:

        criterion_data = criteria.get(
            criterion,
            {},
        )

        avg_impact = criterion_data.get("avg_impact")

        if avg_impact is not None:
            impact_scores.append(avg_impact)

    if impact_scores:

        recommendation_readiness = round((sum(impact_scores) / len(impact_scores)) * 10)

    else:
        recommendation_readiness = 0

    # --------------------------------------------------------
    # Overall AI Readiness
    #
    # Average of:
    #   AI Visibility
    #   Product Readiness
    #   Recommendation Readiness
    # --------------------------------------------------------

    overall = round((ai_visibility + product_readiness + recommendation_readiness) / 3)

    # Add calculated values to scores
    # so email and PDF can use the same function.

    scores["ai_visibility"] = ai_visibility
    scores["product_readiness"] = product_readiness
    scores["recommendation_readiness"] = recommendation_readiness

    return scores, overall


# ============================================================
# EMAIL
# ============================================================


def build_geo_email(data: dict) -> str:
    """
    Build the ContentLynxe AI Visibility email.
    """

    product = (
        data.get(
            "product",
            {},
        )
        or {}
    )

    actual_content = (
        product.get(
            "actual_content",
            {},
        )
        or {}
    )

    product_content = (
        actual_content.get(
            "product_content",
            {},
        )
        or {}
    )

    # --------------------------------------------------------
    # Product name
    # --------------------------------------------------------

    product_name = (
        product_content.get("product_title")
        or product.get("name")
        or product.get("product_name")
        or "Your Product"
    )

    # --------------------------------------------------------
    # First name
    # --------------------------------------------------------

    first_name = data.get("first_name") or product.get("first_name") or "there"

    # --------------------------------------------------------
    # Scores
    # --------------------------------------------------------

    scores, overall = get_scores(product)

    ai_visibility = scores["ai_visibility"]

    product_readiness = scores["product_readiness"]

    recommendation_readiness = scores["recommendation_readiness"]

    overall_ai_readiness = overall

    # --------------------------------------------------------
    # Opportunities
    # --------------------------------------------------------

    opportunities = product.get("opportunities") or []

    if isinstance(
        opportunities,
        dict,
    ):

        opportunity_count = len(opportunities)

    elif isinstance(
        opportunities,
        (list, tuple, set),
    ):

        opportunity_count = len(opportunities)

    else:

        opportunity_count = 0

    # If opportunities are not provided separately,
    # count the available recommendations.

    if opportunity_count == 0:

        opportunity_count = 0

        for criterion in [
            "title",
            "description",
            "attributes",
            "features",
            "assets",
            "pricing",
        ]:

            recommendation = get_best_recommendation(
                product,
                criterion,
            )

            if recommendation:
                opportunity_count += 1

    # --------------------------------------------------------
    # Email HTML
    # --------------------------------------------------------

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ContentLynxe AI Visibility Report</title>
</head>

<body style="
    margin: 0;
    padding: 0;
    background-color: #f6f8fb;
    font-family: Arial, Helvetica, sans-serif;
    color: #222222;
">

<table
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="
        background-color: #f6f8fb;
        padding: 40px 20px;
    "
>
    <tr>
        <td align="center">

            <table
                width="600"
                cellpadding="0"
                cellspacing="0"
                border="0"
                style="
                    width: 100%;
                    max-width: 600px;
                    background-color: #ffffff;
                    border-radius: 10px;
                    padding: 40px;
                "
            >

                <tr>
                    <td
                        style="
                            font-size: 16px;
                            line-height: 1.7;
                            color: #222222;
                        "
                    >

                        <p style="margin: 0 0 24px 0;">
                            Hi {first_name},
                        </p>

                        <p style="margin: 0 0 20px 0;">
                            Thanks for checking out
                            <a
                                href="https://www.contentlynxe.com/"
                                style="
                                    color: #111111;
                                    text-decoration: none;
                                    font-weight: 700;
                                "
                            >
                                ContentLynxe
                            </a>.
                        </p>

                        <p style="margin: 0 0 24px 0;">
                            We analyzed
                            <strong>{product_name}</strong>
                            to see how well its product information is
                            positioned for AI-powered search and
                            recommendations.
                        </p>

                    </td>
                </tr>

                <tr>
                    <td>

                        <h2
                            style="
                                margin: 0 0 18px 0;
                                font-size: 20px;
                                line-height: 1.4;
                                color: #111111;
                            "
                        >
                            Your initial snapshot
                        </h2>

                        <table
                            width="100%"
                            cellpadding="0"
                            cellspacing="0"
                            border="0"
                            style="
                                background-color: #f7f9fc;
                                border-radius: 8px;
                            "
                        >

                            <tr>
                                <td
                                    style="
                                        padding: 12px 18px;
                                        font-size: 15px;
                                        color: #555555;
                                    "
                                >
                                    AI Visibility:
                                </td>

                                <td
                                    align="right"
                                    style="
                                        padding: 12px 18px;
                                        font-size: 15px;
                                        font-weight: 700;
                                        color: #222222;
                                    "
                                >
                                    {ai_visibility}%
                                </td>
                            </tr>

                            <tr>
                                <td
                                    style="
                                        padding: 12px 18px;
                                        font-size: 15px;
                                        color: #555555;
                                    "
                                >
                                    Product Readiness:
                                </td>

                                <td
                                    align="right"
                                    style="
                                        padding: 12px 18px;
                                        font-size: 15px;
                                        font-weight: 700;
                                        color: #222222;
                                    "
                                >
                                    {product_readiness}%
                                </td>
                            </tr>

                            <tr>
                                <td
                                    style="
                                        padding: 12px 18px;
                                        font-size: 15px;
                                        color: #555555;
                                    "
                                >
                                    Recommendation Readiness:
                                </td>

                                <td
                                    align="right"
                                    style="
                                        padding: 12px 18px;
                                        font-size: 15px;
                                        font-weight: 700;
                                        color: #222222;
                                    "
                                >
                                    {recommendation_readiness}%
                                </td>
                            </tr>

                            <tr>
                                <td
                                    style="
                                        padding: 14px 18px;
                                        font-size: 15px;
                                        color: #222222;
                                        font-weight: 700;
                                        border-top: 1px solid #e5e7eb;
                                    "
                                >
                                    Overall AI Readiness:
                                </td>

                                <td
                                    align="right"
                                    style="
                                        padding: 14px 18px;
                                        font-size: 17px;
                                        font-weight: 700;
                                        color: #111111;
                                        border-top: 1px solid #e5e7eb;
                                    "
                                >
                                    {overall_ai_readiness}%
                                </td>
                            </tr>

                        </table>

                    </td>
                </tr>

                <tr>
                    <td
                        style="
                            padding-top: 28px;
                            font-size: 16px;
                            line-height: 1.7;
                            color: #222222;
                        "
                    >

                        <p style="margin: 0 0 20px 0;">
                            We also identified
                            <strong>
                                {opportunity_count} key opportunities
                            </strong>
                            that could improve how AI understands and
                            recommends your product.
                        </p>

                        <p style="margin: 0 0 20px 0;">
                            We've attached your
                            <strong>
                                ContentLynxe AI Visibility Snapshot
                            </strong>
                            with the key findings and recommended actions.
                        </p>

                        <p style="margin: 0 0 28px 0;">
                            If you'd like, we can also walk you through the
                            <strong>full report</strong>
                            and show exactly where your product can improve.
                        </p>

                    </td>
                </tr>

                <tr>
                    <td
                        style="
                            border-top: 1px solid #eeeeee;
                            padding-top: 24px;
                            font-size: 14px;
                            line-height: 1.7;
                            color: #555555;
                        "
                    >

                        <p style="margin: 0 0 4px 0;">
                            Best Regards,
                        </p>

                        <p style="margin: 0 0 18px 0;">
                            <strong>
                                Team
                                <a
                                    href="https://www.contentlynxe.com/"
                                    style="
                                        color: #222222;
                                        text-decoration: none;
                                    "
                                >
                                    ContentLynxe
                                </a>
                            </strong>
                        </p>

                        <p
                            style="
                                margin: 0 0 4px 0;
                                font-style: italic;
                            "
                        >
                            An
                            <a
                                href="https://uniqnex360.com/"
                                style="
                                    color: #555555;
                                    text-decoration: none;
                                "
                            >
                                UniqNex360
                            </a>
                            product
                        </p>

                        <p style="margin: 0;">
                            <a
                                href="mailto:growth@contentlynxe.com"
                                style="
                                    color: #555555;
                                    text-decoration: none;
                                "
                            >
                                growth@contentlynxe.com
                            </a>
                        </p>

                    </td>
                </tr>

            </table>

        </td>
    </tr>
</table>

</body>
</html>
"""


# ============================================================
# PDF
# ============================================================


def generate_ai_visibility_pdf(
    product_data: dict,
) -> bytes:
    """
    Generate the PDF directly from the actual API JSON.

    No temporary file is created.
    """

    product_name = clean_pdf_text(
        product_data.get(
            "name",
            "Your Product",
        )
    )

    # SAME get_scores() USED BY EMAIL
    scores, overall = get_scores(product_data)

    ai_visibility = scores["ai_visibility"]

    product_readiness = scores["product_readiness"]

    recommendation_readiness = scores["recommendation_readiness"]

    pdf = FPDF(format="A4")

    pdf.set_auto_page_break(
        auto=True,
        margin=15,
    )

    # ========================================================
    # PAGE 1
    # ========================================================

    pdf.add_page()

    # --------------------------------------------------------
    # OPTIONAL IMAGE / LOGO
    #
    # Put your image URL here.
    #
    # Example:
    # image_url = "https://your-domain.com/logo.png"
    #
    # Nothing is saved to disk.
    # --------------------------------------------------------

    image_url = (
        "https://res.cloudinary.com/dh75n51on/image/upload/v1789735442/logo_xtodvn.png"
    )

    if image_url:

        try:

            response = requests.get(
                image_url,
                timeout=10,
            )

            response.raise_for_status()

            image_bytes = BytesIO(response.content)

            pdf.image(
                image_bytes,
                x=85,
                y=10,
                w=40,
            )

            pdf.ln(35)

        except Exception:

            # If image URL fails, continue generating
            # the PDF without the image.

            pdf.ln(5)

    else:

        pdf.ln(5)

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    pdf.set_font(
        "Helvetica",
        "B",
        24,
    )

    pdf.cell(
        0,
        12,
        "ContentLynxe",
        align="C",
    )

    pdf.ln(8)

    pdf.set_font(
        "Helvetica",
        "",
        9,
    )

    pdf.cell(
        0,
        6,
        "OPTIMIZE. ENGAGE. GROW.",
        align="C",
    )

    pdf.ln(10)

    pdf.set_font(
        "Helvetica",
        "B",
        20,
    )

    pdf.cell(
        0,
        10,
        "AI Visibility Snapshot",
        align="C",
    )

    pdf.ln(8)

    pdf.set_font(
        "Helvetica",
        "",
        10,
    )

    pdf.multi_cell(
        0,
        6,
        "How the product appears across AI-powered " "search and recommendations",
        align="C",
    )

    pdf.ln(8)

    # ========================================================
    # EXECUTIVE SUMMARY
    # ========================================================

    pdf.set_font(
        "Helvetica",
        "B",
        14,
    )

    pdf.cell(
        0,
        8,
        "01 Executive Summary",
    )

    pdf.ln(8)

    pdf.set_font(
        "Helvetica",
        "",
        10,
    )

    pdf.multi_cell(
        0,
        6,
        f"We analyzed {product_name} to understand how well "
        "its product information is positioned for "
        "AI-powered search and recommendations.",
    )

    pdf.ln(6)

    # ========================================================
    # SUMMARY SCORE TABLE
    # ========================================================

    summary = [
        (
            "AI Visibility",
            ai_visibility,
        ),
        (
            "Product Readiness",
            product_readiness,
        ),
        (
            "Recommendation Readiness",
            recommendation_readiness,
        ),
        (
            "Overall AI Readiness",
            overall,
        ),
    ]

    pdf.set_font(
        "Helvetica",
        "B",
        8,
    )

    for label, score in summary:

        pdf.cell(
            47.5,
            8,
            label,
            border=1,
            align="C",
        )

    pdf.ln()

    pdf.set_font(
        "Helvetica",
        "B",
        14,
    )

    for label, score in summary:

        pdf.cell(
            47.5,
            11,
            f"{score}%",
            border=1,
            align="C",
        )

    pdf.ln(15)

    # ========================================================
    # PRODUCT UNDERSTANDING
    # ========================================================

    pdf.set_font(
        "Helvetica",
        "B",
        14,
    )

    pdf.cell(
        0,
        8,
        "02 Product Understanding Scores",
    )

    pdf.ln(8)

    pdf.set_font(
        "Helvetica",
        "",
        9,
    )

    pdf.multi_cell(
        0,
        6,
        "Scores below are calculated directly from the "
        "aggregate criterion scores returned by the "
        "ContentLynxe recommendation engine.",
    )

    pdf.ln(5)

    # --------------------------------------------------------
    # TABLE HEADER
    # --------------------------------------------------------

    pdf.set_font(
        "Helvetica",
        "B",
        8,
    )

    pdf.cell(
        40,
        8,
        "Criteria",
        border=1,
    )

    pdf.cell(
        20,
        8,
        "Score",
        border=1,
        align="C",
    )

    pdf.cell(
        35,
        8,
        "Status",
        border=1,
        align="C",
    )

    pdf.cell(
        95,
        8,
        "Key observation",
        border=1,
    )

    pdf.ln()

    # --------------------------------------------------------
    # ONLY THE CRITERIA WE ACTUALLY HAVE
    #
    # Removed:
    # Specifications
    # FAQs
    # Reviews
    # Schema
    # --------------------------------------------------------

    criteria_rows = [
        (
            "Title",
            scores["title"],
            "Title clarity and product identity.",
        ),
        (
            "Description",
            scores["description"],
            "Product description depth and relevance.",
        ),
        (
            "Attributes",
            scores["attributes"],
            "Completeness of product attributes.",
        ),
        (
            "Features",
            scores["features"],
            "Coverage of important product features.",
        ),
        (
            "Images",
            scores["assets"],
            "Asset/image readiness.",
        ),
        (
            "Pricing",
            scores["pricing"],
            "Pricing information readiness.",
        ),
    ]

    # --------------------------------------------------------
    # DRAW TABLE ROWS
    #
    # Calculate row height first so all borders stay aligned.
    # --------------------------------------------------------

    pdf.set_font(
        "Helvetica",
        "",
        8,
    )

    for label, score, observation in criteria_rows:

        # FIX: clean text BEFORE dry_run.
        observation = clean_pdf_text(observation)

        # Calculate required height for observation.
        row_height = pdf.multi_cell(
            95,
            7,
            observation,
            dry_run=True,
            output=MethodReturnValue.HEIGHT,
        )

        row_height = max(
            7,
            row_height,
        )

        x = pdf.get_x()
        y = pdf.get_y()

        # Criteria
        pdf.cell(
            40,
            row_height,
            label,
            border=1,
        )

        # Score
        pdf.cell(
            20,
            row_height,
            f"{score}%",
            border=1,
            align="C",
        )

        # Status
        pdf.cell(
            35,
            row_height,
            get_status(score),
            border=1,
            align="C",
        )

        # Observation
        pdf.multi_cell(
            95,
            7,
            observation,
            border=1,
            new_x="LMARGIN",
            new_y="NEXT",
        )

    pdf.ln(10)

    # ========================================================
    # AI SEARCH VISIBILITY
    # ========================================================

    pdf.set_font(
        "Helvetica",
        "B",
        14,
    )

    pdf.cell(
        0,
        8,
        "03 AI Search Visibility",
    )

    pdf.ln(8)

    pdf.set_font(
        "Helvetica",
        "",
        9,
    )

    pdf.multi_cell(
        0,
        6,
        f"Overall AI Visibility Score: {ai_visibility}%",
    )

    pdf.ln(5)

    pdf.set_font(
        "Helvetica",
        "B",
        8,
    )

    # --------------------------------------------------------
    # AI SEARCH TABLE
    # --------------------------------------------------------

    pdf.cell(
        65,
        8,
        "Signal",
        border=1,
    )

    pdf.cell(
        30,
        8,
        "Score",
        border=1,
        align="C",
    )

    pdf.cell(
        65,
        8,
        "Status",
        border=1,
    )

    pdf.ln()

    pdf.set_font(
        "Helvetica",
        "",
        8,
    )

    # We now have enough metrics to calculate
    # meaningful signal scores.

    ai_rows = [
        (
            "Product discovery",
            scores["title"],
        ),
        (
            "Product understanding",
            product_readiness,
        ),
        (
            "Brand association",
            scores["attributes"],
        ),
        (
            "Content relevance",
            scores["description"],
        ),
    ]

    for signal, score in ai_rows:

        pdf.cell(
            65,
            8,
            signal,
            border=1,
        )

        pdf.cell(
            30,
            8,
            f"{score}%",
            border=1,
            align="C",
        )

        pdf.cell(
            65,
            8,
            get_status(score),
            border=1,
        )

        pdf.ln()

        # ========================================================
    # PAGE 2
    # ========================================================

    pdf.add_page()

    # ========================================================
    # ACTION PLAN & PRIORITY
    # ========================================================

    pdf.set_font(
        "Helvetica",
        "B",
        14,
    )

    pdf.cell(
        0,
        8,
        "04 Action Plan & Priority",
    )

    pdf.ln(8)

    pdf.set_font(
        "Helvetica",
        "",
        9,
    )

    pdf.multi_cell(
        0,
        6,
        "Recommended actions are consolidated below with "
        "their corresponding priority so the same recommendation "
        "is not repeated across separate sections.",
    )

    pdf.ln(5)

    pdf.set_font(
        "Helvetica",
        "B",
        8,
    )

    # --------------------------------------------------------
    # TABLE HEADER
    # --------------------------------------------------------

    pdf.cell(
        30,
        8,
        "Criteria",
        border=1,
    )

    pdf.cell(
        20,
        8,
        "Score",
        border=1,
        align="C",
    )

    pdf.cell(
        30,
        8,
        "Priority",
        border=1,
        align="C",
    )

    pdf.cell(
        95,
        8,
        "Action / Finding",
        border=1,
    )

    pdf.ln()

    pdf.set_font(
        "Helvetica",
        "",
        8,
    )

    # --------------------------------------------------------
    # PRIORITY ROWS
    # --------------------------------------------------------

    priority_rows = [
        (
            "Title",
            "title",
            scores["title"],
        ),
        (
            "Description",
            "description",
            scores["description"],
        ),
        (
            "Attributes",
            "attributes",
            scores["attributes"],
        ),
        (
            "Features",
            "features",
            scores["features"],
        ),
        (
            "Images",
            "assets",
            scores["assets"],
        ),
        (
            "Pricing",
            "pricing",
            scores["pricing"],
        ),
    ]

    for label, criterion, score in priority_rows:

        recommendation = get_best_recommendation(
            product_data,
            criterion,
        )

        if recommendation:

            action = recommendation.get("action") or recommendation.get(
                "recommendation",
                "See recommendation.",
            )

        else:

            action = "No recommendation available."

        # FIX: clean AI-generated text BEFORE dry_run.
        action = clean_pdf_text(action)

        # Calculate row height first.
        row_height = pdf.multi_cell(
            95,
            7,
            action,
            dry_run=True,
            output=MethodReturnValue.HEIGHT,
        )

        row_height = max(
            7,
            row_height,
        )

        # Criteria
        pdf.cell(
            30,
            row_height,
            label,
            border=1,
        )

        # Score
        pdf.cell(
            20,
            row_height,
            f"{score}%",
            border=1,
            align="C",
        )

        # Priority
        pdf.cell(
            30,
            row_height,
            get_priority(score),
            border=1,
            align="C",
        )

        # Action / Finding
        pdf.multi_cell(
            95,
            7,
            action,
            border=1,
            new_x="LMARGIN",
            new_y="NEXT",
        )

    pdf.ln(10)

    # ========================================================
    # FOOTER
    # ========================================================

    pdf.set_font(
        "Helvetica",
        "",
        9,
    )

    pdf.cell(
        0,
        6,
        "The complete AI Visibility Report is attached for your reference.",
        align="C",
    )

    # ========================================================
    # RETURN BYTES
    # ========================================================

    return bytes(pdf.output())
