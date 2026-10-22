"""
Judgment calls live here so they are easy to review and change.

classify(slug) -> (bucket, exclude_reason)
  - exclude_reason is None when the place is a plausible sponsor target.
  - Anything not matched falls into bucket "other" (review these in reports/category_review.csv).

Matching is by whole word (the slug split on "_"), never by substring,
so "bar" does not match "barber" and "park" does not match "parking".
"""

# --- Not sponsor targets (exact category slugs) -----------------------------------------------
EXCLUDE_EXACT = {
    # schools / education institutions (they are the audience, not the sponsor)
    **{s: "school" for s in [
        "elementary_school", "middle_school", "high_school", "public_school", "school",
        "school_district_office", "board_of_education_office", "charter_school", "private_school",
        "college_university", "university_housing", "campus_building", "student_union", "library",
        "school_sport_team", "medical_school", "dentistry_school", "law_school", "business_school",
        "engineering_school", "medical_sciences_school", "religious_school", "montessori_school",
    ]},
    # nonprofits / civic groups (beneficiaries or partners, not paying sponsors)
    **{s: "nonprofit_civic" for s in [
        "social_or_community_service", "social_and_human_service", "charity_organization",
        "civic_organization", "youth_organization", "food_bank", "homeless_shelter", "community_center",
        "community_garden", "volunteer_association", "veterans_organization", "fraternal_organization",
        "labor_union", "political_organization", "political_party_office", "private_association",
        "non_governmental_association", "lodge", "housing_cooperative", "homeowner_association",
        "environmental_conservation_organization", "animal_shelter", "animal_rescue_service",
        "adoption_service", "foster_care_service", "child_protection_service", "family_service_center",
        "social_welfare_center", "disability_services_and_support_organization",
        "senior_citizen_service", "agricultural_cooperative", "chambers_of_commerce",
        "crisis_intervention_service", "religious_organization", "place_of_worship",
    ]},
    # government / infrastructure
    **{s: "government_infrastructure" for s in [
        "government_office", "community_and_government", "department_of_motor_vehicles",
        "post_office", "town_hall", "health_department", "immigration_and_naturalization_office",
        "social_security_service", "housing_authority", "public_safety_service",
        "ambulance_or_ems_service", "emergency_department", "public_transit_facility_or_service",
        "bus_station", "train_station", "airport_terminal", "airport", "heliport",
        "rail_facility_or_service", "courthouse", "fire_station", "police_station",
    ]},
    # machines, parking, residential
    **{s: "machine_or_residential" for s in [
        "atm", "package_locker", "rental_kiosk", "kiosk", "ev_charging_station", "parking",
        "parking_lot", "parking_garage", "public_restroom", "apartment", "condominium",
        "mobile_home_park", "service_apartment", "holiday_rental_home",
    ]},
    # public land / nature
    **{s: "public_land" for s in [
        "park", "state_park", "national_park", "dog_park", "skate_park", "nature_reserve",
        "hiking_trail", "mountain_bike_trail", "public_plaza", "playground", "swimming_pool",
        "geographic_entities", "garden", "botanical_garden",
    ]},
}

# Whole-word tokens that mark a category as non-targetable
EXCLUDE_TOKENS = {
    "worship": "religious", "cemetery": "government_infrastructure", "trail": "public_land",
    "lake": "public_land", "river": "public_land", "mountain": "public_land",
    "waterfall": "public_land", "beach": "public_land", "forest": "public_land",
    "bridge": "public_land", "pier": "public_land", "monument": "public_land",
    "fountain": "public_land", "historic": "public_land", "court": "public_land",
    "field": "public_land", "stadium": "public_land", "military": "government_infrastructure",
    "jail": "government_infrastructure", "prison": "government_infrastructure",
    "embassy": "government_infrastructure", "police": "government_infrastructure",
    "locker": "machine_or_residential", "parking": "machine_or_residential",
}

# Category slugs whose bucket the keyword rules get wrong
BUCKET_OVERRIDES = {
    "rv_park": "lodging_recreation", "funeral_service": "business_services",
    "home_service": "home_trades", "interior_design": "home_trades", "key_and_locksmith": "home_trades",
    "engineering_service": "business_services", "rental_service": "business_services",
    "garbage_collection_service": "business_services", "print_media": "business_services",
    "arts_and_entertainment": "lodging_recreation", "laundromat": "personal_care_fitness",
}

# --- Buckets (first match wins, so order matters) ---------------------------------------------
BUCKET_RULES = [
    ("food_drink", {
        "restaurant", "cafe", "bakery", "pizza", "coffee", "diner", "deli", "delicatessen",
        "caterer", "brewery", "bar", "pub", "winery", "distillery", "donut", "bagel", "steakhouse",
        "sushi", "buffet", "bistro", "gastropub", "smoothie", "dessert", "cupcake", "pretzel",
        "popcorn", "chocolatier", "butcher", "tapas", "sandwich", "cafeteria", "brunch", "ramen",
        "bbq", "barbecue", "cream", "gelato", "juice", "tea", "taco", "food", "taqueria", "cheesesteak",
    }),
    ("legal", {"law", "attorney", "legal", "lawyer", "litigation", "notary", "bail", "mediator", "paralegal"}),
    ("financial", {
        "bank", "credit", "insurance", "financial", "mortgage", "accountant", "accounting", "tax",
        "investing", "investment", "loan", "loans", "lender", "bookkeeper", "payroll", "broker",
        "trusts", "advising", "debt", "currency", "escrow", "money",
    }),
    ("tech_telecom", {
        "software", "it", "information", "technology", "computer", "telecommunications", "internet",
        "web", "digital", "data", "biotechnology", "electronics",
    }),
    ("real_estate", {"real", "estate", "property", "realtor", "appraisal", "developer", "apartment"}),
    ("personal_care_fitness", {
        "salon", "spa", "barber", "beauty", "nail", "massage", "tanning", "tattoo", "piercing",
        "waxing", "threading", "eyelash", "gym", "fitness", "yoga", "pilates", "martial", "karate",
        "taekwondo", "boxing", "dance", "weight", "wellness", "cosmetic", "makeup", "skin", "hair",
        "laser", "barre", "cycling",
    }),
    ("pets_animals", {"pet", "pets", "animal", "veterinarian", "veterinary", "dog", "horse", "equestrian", "livestock"}),
    ("health", {
        "doctor", "doctors", "dental", "dentistry", "dentist", "clinic", "health", "healthcare",
        "hospital", "pharmacy", "drugstore", "chiropractic", "physical", "therapy", "medical",
        "surgery", "optometry", "orthodontics", "orthopedics", "counseling", "hospice", "dialysis",
        "podiatry", "audiology", "nursing", "acupuncture", "psychology", "psychiatry",
        "psychotherapy", "diagnostic", "laboratory", "retirement", "assisted", "rehabilitation", "outpatient",
        "practice", "medicine", "cardiology", "obstetrics", "gynecology", "neurology", "urology", "dermatology",
        "oncology", "radiology", "pediatric", "gastroenterology", "nephrology", "ophthalmology", "pediatrics",
    }),
    ("home_trades", {
        "hvac", "plumbing", "plumber", "electrician", "electrical", "roofing", "contractor",
        "landscaping", "lawn", "construction", "builder", "building", "remodeling", "masonry",
        "painting", "paving", "flooring", "carpet", "tile", "tiling", "siding", "windows", "gutter",
        "fence", "handyman", "cleaning", "pest", "pool", "septic", "excavation", "demolition",
        "drywall", "insulation", "garage", "door", "glass", "restoration", "roof", "tree", "junk",
        "countertop", "cabinet", "gardener", "concrete", "propane",
    }),
    ("manufacturing", {
        "manufacturer", "manufacturing", "fabricator", "fabrication", "machine", "machinery",
        "industrial", "plastics", "plastic", "chemical", "textile", "mill", "metal", "steel",
        "foundry", "packaging", "welder", "welding", "machining",
    }),
    ("logistics", {
        "freight", "trucking", "shipping", "courier", "delivery", "mover", "moving", "logistics",
        "warehouse", "distribution", "cargo", "storage", "wholesaler", "supplier", "distributor",
    }),
    ("auto", {
        "auto", "automotive", "car", "tire", "truck", "motorcycle", "trailer", "rv", "vehicle",
        "boat", "dealer", "towing", "oil", "transmission", "brake", "muffler", "collision",
        "windshield", "tractor",
    }),
    ("lodging_recreation", {
        "hotel", "motel", "inn", "lodging", "resort", "bed", "breakfast", "campground", "cabin",
        "cottage", "golf", "bowling", "arcade", "amusement", "theatre", "theater", "movie", "museum",
        "venue", "escape", "zoo", "aquarium", "race", "racing", "rink", "recreation", "sports",
        "sport", "climbing", "paintball", "karaoke", "casino", "event", "party", "wedding",
        "photography", "esports", "travel", "gallery",
    }),
    ("education_childcare", {
        "school", "tutoring", "tutor", "academy", "training", "lessons", "education", "educational",
        "camp", "daycare", "preschool", "childcare", "child", "learning",
    }),
    ("business_services", {
        "professional", "consulting", "consultant", "office", "b2b", "agency", "staffing",
        "employment", "printing", "marketing", "advertising", "funeral", "utility",
    }),
    ("retail", {
        "store", "shop", "retail", "boutique", "market", "mall", "outlet", "grocery", "supermarket",
        "superstore", "showroom", "florist", "flowers", "jewelry", "gift", "gas", "station",
        "convenience", "pawn", "antique", "shopping",
    }),
    ("agriculture", {"farm", "agricultural", "agriculture", "nursery", "greenhouse", "ranch"}),
]


def classify(slug):
    """Return (bucket, exclude_reason) for an Overture category slug."""
    if slug is None or str(slug).strip() == "" or slug == "(none)":
        return "unknown", "no_category"
    if slug in EXCLUDE_EXACT:
        return "excluded", EXCLUDE_EXACT[slug]
    if slug in BUCKET_OVERRIDES:
        return BUCKET_OVERRIDES[slug], None
    tokens = set(slug.split("_"))
    for tok, reason in EXCLUDE_TOKENS.items():
        if tok in tokens:
            return "excluded", reason
    for bucket, words in BUCKET_RULES:
        if tokens & words:
            return bucket, None
    return "other", None


# --- Scoring (starting point, tune freely; not validated against real sponsor outcomes) --------
BUCKET_LABELS = {
    "food_drink": "Food & drink", "legal": "Legal", "financial": "Financial", "tech_telecom": "Tech & telecom",
    "real_estate": "Real estate", "personal_care_fitness": "Personal care & fitness",
    "pets_animals": "Pets & animals", "health": "Health", "home_trades": "Home & trades",
    "manufacturing": "Manufacturing", "logistics": "Logistics", "auto": "Auto",
    "lodging_recreation": "Lodging & recreation", "education_childcare": "Education & childcare",
    "business_services": "Business services", "retail": "Retail", "agriculture": "Agriculture",
    "other": "Other", "school_provided": "School-provided",
}

# Points for category fit (max 25). Based on what Justin said: restaurants are an easy in-kind win,
# and sponsors tied to what students learn (manufacturing, tech, trades) are ideal.
BUCKET_FIT = {
    "food_drink": 25, "manufacturing": 25, "tech_telecom": 22, "auto": 20, "financial": 20,
    "health": 18, "home_trades": 18, "legal": 18, "logistics": 15, "pets_animals": 15,
    "personal_care_fitness": 12, "retail": 12, "real_estate": 12, "lodging_recreation": 12,
    "business_services": 12, "agriculture": 10, "education_childcare": 8, "other": 8,
}

BUCKET_NOTES = {
    "food_drink": "can donate meals or giveaways",
    "manufacturing": "could connect students to jobs",
    "tech_telecom": "could connect students to jobs",
    "home_trades": "trades students could train for",
    "auto": "dealers and career link",
    "financial": "credit unions have sponsored before",
    "legal": "law firms have sponsored before",
}


# --- Solo practitioners (individual people listed as businesses) -------------------------------
# These are poor sponsor targets, so the app hides them by default and ranks them lower if shown.
INDIVIDUAL_NAME_PATTERN = (
    r"(?:^dr\.?\s(?!pepper))|(?:[\s,](?:md|m\.d\.|dds|dmd|d\.o\.|np|np-c|fnp|fnp-c|pa-c|cnm|phd|psyd|lcsw|whnp|aprn|crna|c-e)(?:[\s,.]|$))"
)
INDIVIDUAL_CATEGORIES = {
    "doctors_office", "family_practice", "internal_medicine", "obstetrics_and_gynecology",
    "cardiology", "oral_and_maxillofacial_surgery", "naturopathic_medicine",
}
BUSINESS_WORDS_PATTERN = (
    r"\b(?:clinic|center|centre|group|associates|medical|health|healthcare|care|family|pediatrics|institute|"
    r"hospital|llc|inc|pllc|partners|specialists|physicians|practice|urgent|ortho|orthopedic|cardiology)\b"
)