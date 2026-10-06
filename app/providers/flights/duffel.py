import os
import re

from app.core.errors import AppError
from app.models import Flight, Passenger, SearchFlights, BookFlight, Stop, Airport, Cabin, BookingResult
from .base import FlightProvider

import httpx
from dotenv import load_dotenv

load_dotenv()


class DuffelFlightProvider(FlightProvider):
    def __init__(self):
        self.token = os.getenv("FLIGHT_VENDOR_TOKEN")
        
        if not self.token:
            raise RuntimeError("FLIGHT_VENDOR_TOKEN is not set")
        
        self.base_url = "https://api.duffel.com"
        
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Duffel-Version": "v2",
        }
        
    async def search_flights(self, request: SearchFlights) -> list[Flight]:
        payload = {
            "data": {
                "slices": [
                    {
                        "origin": request.origin,
                        "destination": request.destination,
                        "departure_date": request.date.isoformat(),
                    }
                ],
                "passengers": [
                    {"type": "adult"}
                    for _ in range(request.passengers)
                ],
                "cabin_class": request.cabin.value,
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/air/offer_requests",
                headers=self.headers,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()

            offer_request_id = response.json()["data"]["id"]

            offers_response = await client.get(
                f"{self.base_url}/air/offers",
                headers=self.headers,
                params={
                    "offer_request_id": offer_request_id,
                },
                timeout=30,
            )

            offers_response.raise_for_status()

            offers = offers_response.json()["data"]

        return [map_duffel_offer(offer) for offer in offers]

    async def book_flight(
        self,
        request: BookFlight,
        flight: Flight,
        passengers: list[Passenger],
    ) -> BookingResult:
        offer = await self._fetch_raw_offer(flight.provider_reference)
        
        if offer["payment_requirements"]["requires_instant_payment"]:
            raise AppError(
                "This flight offer requires instant payment and cannot be held."
            )

        offer_passengers = offer["passengers"]

        if len(offer_passengers) != len(passengers):
            raise AppError(
                "Passenger count does not match the selected flight offer."
            )

        duffel_passengers = []

        for offer_passenger, passenger in zip(
            offer_passengers,
            passengers,
        ):
            duffel_passengers.append({
                "id": offer_passenger["id"],
                "title": passenger.title,
                "given_name": passenger.given_name,
                "family_name": passenger.family_name,
                "gender": passenger.gender,
                "born_on": passenger.born_on.isoformat(),
                "email": passenger.email,
                "phone_number": passenger.phone_number,
            })

        payload = {
            "data": {
                "type": "hold",
                "selected_offers": [
                    flight.provider_reference
                ],
                "passengers": duffel_passengers,
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/air/orders",
                headers=self.headers,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()

            result = response.json()["data"]
            return BookingResult(
                booking_id=result["id"],
                booking_reference=result["booking_reference"],
                status=result["type"],
                total_amount=float(result["total_amount"]),
                currency=result["total_currency"],
                payment_required_by=result["payment_status"].get("payment_required_by")
            )

    async def cancel_order(self, provider_booking_id: str) -> None:
        """Duffel cancels in two steps: create a cancellation quote, then confirm it."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/air/order_cancellations",
                headers=self.headers,
                json={"data": {"order_id": provider_booking_id}},
                timeout=30,
            )
            response.raise_for_status()

            cancellation_id = response.json()["data"]["id"]

            confirm = await client.post(
                f"{self.base_url}/air/order_cancellations/{cancellation_id}/actions/confirm",
                headers=self.headers,
                timeout=30,
            )
            confirm.raise_for_status()

    async def fetch_flight_details(self, flight_id: str) -> Flight | None:
        result = await self._fetch_raw_offer(flight_id)
        return map_duffel_offer(result)
    
    async def _fetch_raw_offer(
        self,
        provider_reference: str,
    ) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/air/offers/{provider_reference}",
                headers=self.headers,
                timeout=30,
            )

            response.raise_for_status()

            return response.json()["data"]
    

def map_duffel_offer(offer: dict) -> Flight:
    slice_ = offer["slices"][0]
    segments = slice_["segments"]

    first_segment = segments[0]
    last_segment = segments[-1]

    origin_data = slice_["origin"]
    destination_data = slice_["destination"]

    origin = Airport(
        airport_name=origin_data["name"],
        airport_code=origin_data["iata_code"],
    )

    destination = Airport(
        airport_name=destination_data["name"],
        airport_code=destination_data["iata_code"],
    )

    stops = []

    for index, segment in enumerate(segments[:-1]):
        next_segment = segments[index + 1]

        stops.append(
            Stop(
                airport=Airport(
                    airport_name=segment["destination"]["name"],
                    airport_code=segment["destination"]["iata_code"],
                ),
                arrival_datetime=segment["arriving_at"],
                departure_datetime=next_segment["departing_at"],
            )
        )

    cabin = Cabin(
        first_segment["passengers"][0]["cabin"]["name"]
    )

    payment_requirements = offer.get("payment_requirements", {})
    
    return Flight(
        flight_id=offer["id"],
        provider_reference=offer["id"],
        flight_name=offer["owner"]["name"],
        origin=origin,
        destination=destination,
        departure_datetime=first_segment["departing_at"],
        arrival_datetime=last_segment["arriving_at"],
        price=float(offer["total_amount"]),
        currency=offer["total_currency"],
        cabin=cabin,
        available_seats=None,
        expires_at=offer.get("expires_at"),
        requires_instant_payment=payment_requirements.get(
            "requires_instant_payment"
        ),
        payment_required_by=payment_requirements.get(
            "payment_required_by"
        ),
        duration_minutes=parse_iso_duration(slice_.get("duration")),
        stops=stops,
    )

_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")


def parse_iso_duration(value: str | None) -> int | None:
    """'PT3H29M' -> 209, 'P1DT2H' -> 1560. Departure/arrival are local times,
    so the provider's duration is the only correct flight length."""
    if not value:
        return None

    match = _DURATION.match(value)
    if not match:
        return None

    days, hours, minutes = (int(part or 0) for part in match.groups())
    return days * 1440 + hours * 60 + minutes
