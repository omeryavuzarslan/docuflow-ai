"""Fixed, hand-written reference data: fictional UK companies and their products.

Hand-written rather than Faker: no extra dependency, nothing that can drift between
library versions, and every value is plausible for B2B purchasing. Company names and VAT
numbers are invented.
"""

from dataclasses import dataclass
from decimal import Decimal

from backend.app.domain.parties import Address, Buyer, Supplier


@dataclass(frozen=True)
class Product:
    """Price and quantity ranges are integers, scaled down: no floats anywhere.

    Unit price is randint(price_low, price_high) * 10**-price_places.
    Quantity is randint(qty_low, qty_high) * qty_step; qty_low >= 2 so a partial
    delivery can always ship at least one step less.
    """

    sku: str
    description: str
    price_low: int
    price_high: int
    price_places: int
    qty_low: int
    qty_high: int
    qty_step: Decimal = Decimal("1")


@dataclass(frozen=True)
class SupplierEntry:
    supplier: Supplier
    products: tuple[Product, ...]


ONE = Decimal("1")
HALF = Decimal("0.5")
FIFTY = Decimal("50")
HUNDRED = Decimal("100")

OFFICE = (
    Product("OF-1001", "A4 copier paper, 80gsm, box of 5 reams", 1899, 2899, 2, 2, 20),
    Product("OF-1002", "Ballpoint pens, blue, box of 50", 699, 1299, 2, 2, 15),
    Product("OF-1003", "Lever arch files, A4, pack of 10", 1450, 2250, 2, 2, 12),
    Product("OF-1004", "Sticky notes 76x76mm, pack of 12", 499, 899, 2, 2, 25),
    Product("OF-1005", "Toner cartridge, black, high yield", 6499, 11999, 2, 2, 6),
    Product("OF-1006", "Whiteboard markers, assorted, pack of 4", 349, 649, 2, 2, 30),
    Product("OF-1007", "Desk organiser, mesh, black", 1199, 1899, 2, 2, 10),
    Product("OF-1008", "Shipping labels, 99x38mm, per label", 120, 260, 4, 4, 40, HUNDRED),
    Product("OF-1009", "Envelopes C4, white, box of 250", 1899, 2999, 2, 2, 8),
    Product("OF-1010", "USB-C cable, 2m", 599, 1199, 2, 2, 20),
)

CLEANING = (
    Product("CL-2001", "Floor cleaner concentrate, per litre", 289, 459, 2, 4, 40, HALF),
    Product("CL-2002", "Centrefeed paper rolls, pack of 6", 1299, 1899, 2, 2, 25),
    Product("CL-2003", "Nitrile gloves, medium, box of 100", 599, 999, 2, 2, 30),
    Product("CL-2004", "Black refuse sacks, roll of 50", 549, 899, 2, 2, 40),
    Product("CL-2005", "Hand soap refill, 5 litre", 999, 1599, 2, 2, 12),
    Product("CL-2006", "Microfibre cloths, pack of 10", 699, 1099, 2, 2, 20),
    Product("CL-2007", "Mop head, cotton, 400g", 349, 599, 2, 2, 15),
    Product("CL-2008", "Disinfectant wipes, tub of 200", 499, 849, 2, 2, 30),
    Product("CL-2009", "Washroom air freshener refill", 249, 449, 2, 2, 24),
)

WAREHOUSE = (
    Product("WH-3001", "Wood screws 4x40mm, per screw", 300, 650, 4, 4, 40, FIFTY),
    Product("WH-3002", "Flat washers M8, per washer", 150, 400, 4, 4, 40, FIFTY),
    Product("WH-3003", "Cable ties 300mm, per tie", 180, 420, 4, 2, 20, HUNDRED),
    Product("WH-3004", "Packing tape, clear, 48mm x 66m", 149, 289, 2, 6, 72),
    Product("WH-3005", "Stretch wrap film, 500mm x 250m", 1099, 1699, 2, 2, 24),
    Product("WH-3006", "Polypropylene twine, per kg", 449, 749, 2, 2, 30, HALF),
    Product("WH-3007", "Double-wall cardboard box, 457x305x305mm", 189, 349, 2, 10, 200),
    Product("WH-3008", "Hi-vis vest, yellow, size L", 299, 599, 2, 2, 25),
    Product("WH-3009", "Safety cutter with retractable blade", 399, 799, 2, 2, 20),
    Product("WH-3010", "Pallet label holder, magnetic", 249, 449, 2, 2, 30),
)


def _supplier(
    name: str, vat: str, line1: str, city: str, postcode: str, products: tuple[Product, ...]
) -> SupplierEntry:
    address = Address(line1=line1, city=city, postcode=postcode)
    return SupplierEntry(Supplier(name=name, vat_number=vat, address=address), products)


SUPPLIERS = (
    _supplier(
        "Kestrel Office Supplies Ltd",
        "GB284716359",
        "Unit 4, Riverside Park",
        "Leeds",
        "LS11 5QD",
        OFFICE,
    ),
    _supplier(
        "Paperline Direct Ltd", "GB519302847", "12 Canal Street", "Manchester", "M1 3HE", OFFICE
    ),
    _supplier(
        "BrightWay Hygiene Ltd",
        "GB736158204",
        "3 Station Road",
        "Bristol",
        "BS1 6QF",
        CLEANING,
    ),
    _supplier(
        "Fenwick Industrial Supplies Ltd",
        "GB402857193",
        "Bay 7, Trafford Trading Estate",
        "Manchester",
        "M17 1RN",
        WAREHOUSE,
    ),
    _supplier(
        "Northgate Packaging Ltd",
        "GB693041528",
        "88 Dock Lane",
        "Hull",
        "HU1 2BT",
        WAREHOUSE,
    ),
)

BUYERS = (
    Buyer(
        name="Harbour & Hale Retail plc",
        vat_number="GB158392046",
        address=Address(line1="20 Cornmarket Street", city="Oxford", postcode="OX1 3HA"),
    ),
    Buyer(
        name="Linden Logistics Ltd",
        vat_number="GB847261930",
        address=Address(line1="Building 2, Meridian Way", city="Coventry", postcode="CV3 4FJ"),
    ),
    Buyer(
        name="Ashcombe Hotels Ltd",
        vat_number="GB370519284",
        address=Address(line1="5 Queen Square", city="Bath", postcode="BA1 2HN"),
    ),
)
