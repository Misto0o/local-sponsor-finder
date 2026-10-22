# 🎯 Local Sponsor Finder

**A school-focused sponsor discovery tool built by Kearns Academy Teamship for Stay Plugged In.**

Local Sponsor Finder helps identify potential local business sponsors near a school. It uses open business data to filter and rank businesses, giving sponsorship teams a starting point for outreach to support esports, STEM, and career education programs.

## ✨ Features

- **Business discovery:** Find businesses near a school's address.
- **Data filtering:** Narrow results using business status, data quality, and sponsor-type criteria.
- **Rules-based ranking:** Prioritize potential sponsors using factors such as category fit, contact information, local versus chain status, and existing school connections.
- **Map visualization:** Explore business locations geographically.
- **Downloadable call lists:** Export results to support outreach.
- **Configurable scoring:** Adjust ranking weights as the project evolves.

## 📊 Prototype Results

In the current prototype run:

| Stage | Businesses |
|---|---:|
| Businesses near the school | 153,428 |
| Open and trustworthy | 119,231 |
| Good sponsor types | 95,889 |
| Meet call-list criteria | 66,793 |

These figures represent the prototype's filtering pipeline, not verified sponsorship opportunities.

## 🛠️ Tech Stack

- **Python** — data processing and ranking logic
- **Streamlit** — interactive web application
- **Overture Maps** — open business data
- **Data filtering and scoring** — rules-based lead prioritization

## 🚀 How It Works

1. Enter a school's address.
2. Find businesses in the surrounding area.
3. Filter businesses using the prototype's criteria.
4. Rank potential sponsors.
5. Explore the results on a map and download a call list.

## ⚠️ Limitations

This project is a prototype. Results are a starting point for research, not a verified lead list.

- Phone numbers and emails are not verified.
- Decision-maker names are not included.
- Community involvement is not yet part of the scoring system.
- Chain detection can occasionally misclassify businesses.
- A high ranking does not guarantee sponsorship interest.

Human review and relationship-building remain essential to successful outreach.

## 🗺️ Data Attribution

Business data © Overture Maps Foundation, licensed under the CDLA-Permissive-2.0 license.

Review the applicable data license and attribution requirements when redistributing data or derived datasets.

## 🎓 Project Background

Developed by Kearns Academy Teamship as a prototype for Stay Plugged In, exploring ways to make local sponsor discovery more efficient and scalable for student programs.

## 📌 Project Status

**Prototype / In development**

Future improvements may include website-based community involvement checks, better contact verification, improved sponsor scoring, and more accurate chain detection.

---

*Built to help connect local businesses with opportunities to support students, esports, STEM, and career pathways.*