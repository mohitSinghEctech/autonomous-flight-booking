import os

from app.models import Flight, SearchFlights, BookFlight, Stop, Airport, Cabin
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

    async def book_flight(self, request: BookFlight) -> dict:
        raise NotImplementedError

    async def fetch_flight_details(self, flight_id: str) -> Flight | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/air/offers/{flight_id}",
                headers=self.headers,
                timeout=30,
            )

            response.raise_for_status()
            
            result = response.json()["data"]
            return map_duffel_offer(result)
    

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

    return Flight(
        flight_id=offer["id"],
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
        stops=stops,
    )