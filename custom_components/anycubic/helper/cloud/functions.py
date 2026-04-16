from __future__ import annotations

import asyncio
from typing import (
    Any,
    Literal,
    overload,
)

from ...const import (
    API_ENDPOINT,
    MAX_PROJECT_IMAGE_SEARCH_COUNT,
    MAX_PROJECT_LIST_RESULTS,
    AnycubicServerMessage,
    AnycubicFeedType,
    AnycubicOrderID,
    AnycubicPrintStatus,
)
from .order_requests import (
    AnycubicBaseOrderRequest,
    AnycubicProjectCtrlOrderRequest,
    AnycubicProjectOrderRequest,
)
from .printer_model import AnycubicPrinter
from .printer_components import AnycubicMaterialColor
from .print_models import AnycubicPrintingSettings
from .project_model import AnycubicProject
from .. import (
    ErrorsAPIParsing,
    ErrorsDataParsing,
    ErrorsFileNotFound,
    ErrorsGeneral,
)
from .exceptions import (
    AnycubicAPIError,
    AnycubicAPIParsingError,
    AnycubicDataParsingError,
    AnycubicFileNotFoundError,
)
from .api import AnycubicAPIBase


class AnycubicAPIFunctions(AnycubicAPIBase):

    @overload
    async def fetch_project_gcode_info_fdm(
        self,
        project_id: int,
    ) -> AnycubicProject | None: ...

    @overload
    async def fetch_project_gcode_info_fdm(
        self,
        project_id: int,
        raw_data: Literal[True] = ...,
    ) -> dict[str, Any]: ...

    async def fetch_project_gcode_info_fdm(
        self,
        project_id: int,
        raw_data: bool = False,
    ) -> AnycubicProject | None | dict[str, Any]:
        query = {
            'id': str(project_id),
        }
        resp = await self._fetch_api_resp(
            endpoint=API_ENDPOINT.project_gcode_info_fdm,
            query=query
        )
        if raw_data:
            return resp

        data = resp['data']

        return AnycubicProject.from_gcode_json(self, data)

    @overload
    async def delete_file_from_cloud(
        self,
        file_id: int,
    ) -> bool: ...

    @overload
    async def delete_file_from_cloud(
        self,
        file_id: int,
        raw_data: Literal[True] = ...,
    ) -> dict[str, Any]: ...

    async def delete_file_from_cloud(
        self,
        file_id: int,
        raw_data: bool = False,
    ) -> bool | dict[str, Any]:
        params = {
            'idArr': [file_id],
        }
        resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.delete_cloud_file, params=params)
        if raw_data:
            return resp

        data = resp['data']

        return True if data == '' else False

    # ORDER Functions
    # ------------------------------------------

    @overload
    async def _send_anycubic_order(
        self,
        order_request: AnycubicBaseOrderRequest,
    ) -> str | None: ...

    @overload
    async def _send_anycubic_order(
        self,
        order_request: AnycubicBaseOrderRequest,
        raw_data: Literal[True] = ...
    ) -> dict[str, Any]: ...

    @overload
    async def _send_anycubic_order(
        self,
        order_request: AnycubicBaseOrderRequest,
        raw_data: bool = False,
    ) -> str | None | dict[str, Any]: ...

    async def _send_anycubic_order(
        self,
        order_request: AnycubicBaseOrderRequest,
        raw_data: bool = False,
    ) -> str | None | dict[str, Any]:
        params = order_request.order_request_data

        for attempt in range(3):
            try:
                resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.send_order, params=params)
            except AnycubicAPIParsingError:
                # Cloud occasionally responds with non-JSON during token rollover or throttling.
                if attempt < 2:
                    try:
                        await self.check_api_tokens()
                    except Exception:
                        pass
                    await asyncio.sleep(0.8)
                    continue
                raise

            error_message = resp.get('msg') if resp is not None else None
            error_message_text = str(error_message or '').strip().lower()
            error_code = int(resp.get('code', -1)) if isinstance(resp, dict) else -1

            # Retry once after refreshing auth when cloud returns expired-login.
            is_expired_login = (
                error_code == 10001
                or 'login information has expired' in error_message_text
            )
            if attempt == 0 and is_expired_login:
                try:
                    refreshed = await self.check_api_tokens()
                except Exception:
                    refreshed = False
                if refreshed:
                    continue

            # Retry on Anycubic's temporary anti-spam/rate-limit responses.
            is_rate_limited = (
                'too frequent' in error_message_text
                or 'too many requests' in error_message_text
                or '请求过于频繁' in str(error_message or '')
            )
            if attempt < 2 and is_rate_limited:
                await asyncio.sleep(1.0)
                continue

            if raw_data:
                return resp

            if resp is not None and resp.get('data') is not None:
                data: str | None = resp['data'].get('msgid')

                if data is None:
                    self._log_to_error(f"Empty reply when sending order to Anycubic Cloud, message: {error_message}")

                return data

            if error_message == AnycubicServerMessage.FILE_NOT_FOUND:
                raise AnycubicFileNotFoundError(ErrorsFileNotFound.in_cloud)

            raise AnycubicAPIError(ErrorsGeneral.send_order_fail.format(error_message))

        return None

    async def _send_order_multi_color_box_set_slot(
        self,
        printer: AnycubicPrinter,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        slot_material_type: str,
        box_id: int = 0,
    ) -> str | None:
        if not printer:
            return None

        slot_params = {
            'color': slot_color.data,
            'index': slot_index,
            'type': slot_material_type,
        }

        order_params = {
            'id': box_id,
            'slots': [
                slot_params,
            ]
        }

        order_data = {
            'multi_color_box': [
                order_params,
            ]
        }

        return await self._send_anycubic_order(
            order_request=AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.MULTI_COLOR_BOX_SET_SLOT,
                printer_id=printer.id,
                project_id=0,
                order_data=order_data,
            ),
        )

    async def _send_order_multi_color_box_feed_filament(
        self,
        printer: AnycubicPrinter,
        slot_index: int,
        feed_type: int,
        box_id: int = 0,
    ) -> str | None:
        if not printer:
            return None

        if feed_type == AnycubicFeedType.Feed and slot_index < 0:
            return None

        if feed_type == AnycubicFeedType.Retract:
            slot_index = -1

        feed_params = {
            'slot_index': slot_index,
            'type': feed_type,
        }

        order_params = {
            'id': box_id,
            'feed_status': feed_params
        }

        order_data = {
            'multi_color_box': [
                order_params,
            ]
        }

        return await self._send_anycubic_order(
            order_request=AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.FEED_FILAMENT,
                printer_id=printer.id,
                project_id=0,
                order_data=order_data,
            ),
        )

    async def _send_order_multi_color_box_dry(
        self,
        printer: AnycubicPrinter,
        order_params: dict[str, Any] | list[dict[str, Any]],
    ) -> str | None:
        if not printer:
            return None

        if not isinstance(order_params, list):
            order_params = [order_params]

        box_list = list()

        for box_id, order in enumerate(order_params):
            box_list.append({
                'drying_status': {
                    'duration': int(order.get('duration', 0)),
                    'remain_time': None,
                    'status': int(order.get('status', 0)),
                    'target_temp': int(order.get('target_temp', 40)),
                },
                'id': int(order.get('box_id', box_id)),
            })

        order_data = {
            'multi_color_box': box_list
        }

        return await self._send_anycubic_order(
            order_request=AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.MULTI_COLOR_BOX_DRY,
                printer_id=printer.id,
                project_id=0,
                order_data=order_data,
            ),
        )

    async def _send_order_multi_color_auto_feed(
        self,
        printer: AnycubicPrinter,
        enabled: bool,
        box_id: int = 0,
    ) -> str | None:
        if not printer:
            return None

        box_list = list([
            {
                'id': box_id,
                'auto_feed': int(enabled),
            }
        ])

        order_data = {
            'multi_color_box': box_list
        }

        return await self._send_anycubic_order(
            order_request=AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.MULTI_COLOR_BOX_AUTO_FEED,
                printer_id=printer.id,
                project_id=0,
                order_data=order_data,
            ),
        )

    async def _send_order_pause_print(
        self,
        printer: AnycubicPrinter,
        project: AnycubicProject,
    ) -> str | None:
        if not printer:
            return None

        if not project:
            return None

        return await self._send_anycubic_order(
            order_request=AnycubicProjectCtrlOrderRequest(
                order_id=AnycubicOrderID.PAUSE_PRINT,
                printer_id=printer.id,
                project_id=project.id,
                order_data=None,
                ams_box_mapping=None,
                print_settings=None,
            ),
        )

    async def _send_order_resume_print(
        self,
        printer: AnycubicPrinter,
        project: AnycubicProject,
    ) -> str | None:
        if not printer:
            return None

        if not project:
            return None

        return await self._send_anycubic_order(
            order_request=AnycubicProjectCtrlOrderRequest(
                order_id=AnycubicOrderID.RESUME_PRINT,
                printer_id=printer.id,
                project_id=project.id,
                order_data=None,
                ams_box_mapping=None,
                print_settings=None,
            ),
        )

    async def _send_order_stop_print(
        self,
        printer: AnycubicPrinter,
        project: AnycubicProject,
    ) -> str | None:
        if not printer:
            return None

        if not project:
            return None

        return await self._send_anycubic_order(
            order_request=AnycubicProjectCtrlOrderRequest(
                order_id=AnycubicOrderID.STOP_PRINT,
                printer_id=printer.id,
                project_id=project.id,
                order_data=None,
                ams_box_mapping=None,
                print_settings=None,
            ),
        )

    async def _send_order_change_print_settings(
        self,
        printer: AnycubicPrinter,
        print_settings: AnycubicPrintingSettings,
        project: AnycubicProject | None = None,
    ) -> str | None:
        if not printer:
            return None

        if project is None:
            project = printer.latest_project

        if project is not None:
            project.validate_new_print_settings(print_settings)

        settings_data = print_settings.settings_data
        order_data = {
            'settings': settings_data
        }

        # Fan-only updates are firmware-dependent: some printers want project_id=0,
        # others only accept a live task id. Try a small set of candidates.
        fan_keys = {'fan_speed_pct', 'aux_fan_speed_pct', 'box_fan_level'}
        is_fan_only_update = bool(settings_data) and set(settings_data.keys()).issubset(fan_keys)

        project_candidates: list[int] = []
        if project is not None:
            project_candidates.append(int(project.id))
        if is_fan_only_update:
            project_candidates.extend([0, -1])
        else:
            project_candidates.append(0)

        # Keep candidate order and remove duplicates.
        ordered_candidates: list[int] = []
        seen: set[int] = set()
        for candidate in project_candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            ordered_candidates.append(candidate)

        last_error: Exception | None = None
        for project_id in ordered_candidates:
            try:
                return await self._send_anycubic_order(
                    order_request=AnycubicProjectOrderRequest(
                        order_id=AnycubicOrderID.PRINT_SETTINGS,
                        printer_id=printer.id,
                        project_id=project_id,
                        order_data=order_data,
                    ),
                )
            except AnycubicAPIError as err:
                last_error = err
                err_text = str(err).lower()
                is_project_missing = (
                    "print task does not exist" in err_text
                    or "project does not exist" in err_text
                    or "项目不存在" in err_text
                )
                if not is_project_missing:
                    raise
                continue

        if last_error is not None:
            raise last_error
        return None

    #
    #
    async def _send_order_set_light_status(
        self,
        printer: AnycubicPrinter,
        project: AnycubicProject | None,
        light_on: bool,
        light_type: int = 1,
    ) -> str | None:
        if not printer:
            return None

        order_data = {
            'type': light_type,
            'status': 1 if light_on else 0,
            'brightness': 100 if light_on else 0,
        }

        project_id = int(project.id) if project is not None else 0

        return await self._send_anycubic_order(
            order_request=AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.SET_LIGHT_STATUS,
                printer_id=printer.id,
                project_id=project_id,
                order_data=order_data,
            ),
        )

    #
    #
    # Main API Functions
    # ------------------------------------------

    async def pause_print(
        self,
        printer: AnycubicPrinter,
        project: AnycubicProject | None = None,
    ) -> str | None:
        if not printer:
            return None

        if not project and not printer.latest_project:
            return None

        if not project:
            project = printer.latest_project

        assert project

        resp = await self._send_order_pause_print(
            printer,
            project,
        )

        return resp

    async def resume_print(
        self,
        printer: AnycubicPrinter,
        project: AnycubicProject | None = None,
    ) -> str | None:
        if not printer:
            return None

        if not project and not printer.latest_project:
            return None

        if not project:
            project = printer.latest_project

        assert project

        resp = await self._send_order_resume_print(
            printer,
            project,
        )

        return resp

    async def cancel_print(
        self,
        printer: AnycubicPrinter,
        project: AnycubicProject | None = None,
    ) -> str | None:
        if not printer:
            return None

        if not project and not printer.latest_project:
            return None

        if not project:
            project = printer.latest_project

        assert project

        resp = await self._send_order_stop_print(
            printer,
            project,
        )

        return resp

    async def multi_color_box_feed_filament(
        self,
        printer: AnycubicPrinter,
        slot_index: int,
        box_id: int = -1,
        finish: bool = False,
    ) -> str | None:
        """
        Must send a finish command when done.
        """
        if not printer:
            return None

        if not printer.primary_multi_color_box:
            return None

        if box_id < 0:
            box_id = 0

        resp = await self._send_order_multi_color_box_feed_filament(
            printer=printer,
            slot_index=slot_index,
            feed_type=(
                AnycubicFeedType.Feed
                if not finish else
                AnycubicFeedType.Finish
            ),
            box_id=box_id,
        )

        return resp

    async def multi_color_box_retract_filament(
        self,
        printer: AnycubicPrinter,
        box_id: int = -1,
    ) -> str | None:
        if not printer:
            return None

        if not printer.primary_multi_color_box:
            return None

        if box_id < 0:
            box_id = 0

        resp = await self._send_order_multi_color_box_feed_filament(
            printer=printer,
            slot_index=-1,
            feed_type=AnycubicFeedType.Retract,
            box_id=box_id,
        )

        return resp

    async def multi_color_box_set_auto_feed(
        self,
        printer: AnycubicPrinter,
        enabled: bool,
        box_id: int = -1,
    ) -> str | None:
        if not printer:
            return None

        if not printer.primary_multi_color_box:
            return None

        if box_id < 0:
            box_id = 0

        resp = await self._send_order_multi_color_auto_feed(
            printer,
            enabled,
            box_id,
        )

        return resp

    async def multi_color_box_toggle_auto_feed(
        self,
        printer: AnycubicPrinter,
        box_id: int = -1,
    ) -> str | None:
        if not printer:
            return None

        if not printer.primary_multi_color_box:
            return None

        if box_id < 0:
            box_id = 0

        assert printer.multi_color_box

        current_auto_feed = bool(printer.multi_color_box[box_id].auto_feed)

        printer.multi_color_box[box_id].set_auto_feed(not current_auto_feed)

        resp = await self._send_order_multi_color_auto_feed(
            printer,
            (not current_auto_feed),
            box_id,
        )

        return resp

    async def multi_color_box_switch_on_auto_feed(
        self,
        printer: AnycubicPrinter,
        box_id: int = -1,
    ) -> str | None:
        if not printer:
            return None

        if not printer.primary_multi_color_box:
            return None

        if box_id < 0:
            box_id = 0

        assert printer.multi_color_box

        current_auto_feed = bool(printer.multi_color_box[box_id].auto_feed)

        if current_auto_feed:
            return None

        printer.multi_color_box[box_id].set_auto_feed(True)

        resp = await self._send_order_multi_color_auto_feed(
            printer,
            True,
            box_id,
        )

        return resp

    async def multi_color_box_switch_off_auto_feed(
        self,
        printer: AnycubicPrinter,
        box_id: int = -1,
    ) -> str | None:
        if not printer:
            return None

        if not printer.primary_multi_color_box:
            return None

        if box_id < 0:
            box_id = 0

        assert printer.multi_color_box

        current_auto_feed = bool(printer.multi_color_box[box_id].auto_feed)

        if not current_auto_feed:
            return None

        printer.multi_color_box[box_id].set_auto_feed(False)

        resp = await self._send_order_multi_color_auto_feed(
            printer,
            False,
            box_id,
        )

        return resp

    async def multi_color_box_set_slot(
        self,
        printer: AnycubicPrinter,
        slot_index: int,
        slot_color: AnycubicMaterialColor | None = None,
        slot_material_type: str = "PLA",
        slot_color_red: int | None = None,
        slot_color_green: int | None = None,
        slot_color_blue: int | None = None,
        box_id: int = 0,
    ) -> str | None:
        if (
            slot_color is None and
            any([x is None for x in [
                slot_color_red,
                slot_color_green,
                slot_color_blue
            ]])
        ):
            raise AnycubicAPIError(ErrorsGeneral.set_slot_color_invalid)

        if slot_color is None:
            assert slot_color_red
            assert slot_color_green
            assert slot_color_blue
            slot_color = AnycubicMaterialColor(
                slot_color_red,
                slot_color_green,
                slot_color_blue,
            )

        return await self._send_order_multi_color_box_set_slot(
            printer=printer,
            slot_index=slot_index,
            slot_color=slot_color,
            slot_material_type=slot_material_type,
            box_id=box_id,
        )

    async def multi_color_box_drying_start(
        self,
        printer: AnycubicPrinter,
        duration: int,
        target_temp: int,
        box_id: int = -1,
    ) -> str | None:
        if not printer:
            return None

        if not printer.primary_multi_color_box:
            return None

        order_params = {
            'duration': duration,
            'target_temp': target_temp,
            'status': 1,
        }
        if box_id > 0:
            order_params['box_id'] = box_id

        resp = await self._send_order_multi_color_box_dry(
            printer,
            order_params,
        )

        return resp

    async def multi_color_box_drying_stop(
        self,
        printer: AnycubicPrinter,
        box_id: int = -1,
    ) -> str | None:
        if not printer:
            return None

        if not printer.primary_multi_color_box:
            return None

        if box_id >= 0:
            order_params: list[dict[str, Any]] | dict[str, Any] = {
                'status': 0,
            }
        else:
            order_params = [
                {
                    'status': 0
                } for x in range(printer.connected_ace_units)
            ]

        resp = await self._send_order_multi_color_box_dry(
            printer,
            order_params,
        )

        return resp

    @overload
    async def list_my_printers(
        self,
        ignore_init_errors: bool = False,
    ) -> list[AnycubicPrinter]: ...

    @overload
    async def list_my_printers(
        self,
        ignore_init_errors: bool = False,
        raw_data: Literal[True] = ...
    ) -> dict[str, Any]: ...

    async def list_my_printers(
        self,
        ignore_init_errors: bool = False,
        raw_data: bool = False,
    ) -> list[AnycubicPrinter] | dict[str, Any]:
        resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.printer_get_printers)
        if raw_data:
            return resp

        data = list([
            AnycubicPrinter.from_status_json(
                self,
                x,
                ignore_init_errors=ignore_init_errors,
            ) for x in resp['data']
        ])
        if ignore_init_errors:
            for x in data:
                if x is None or x.initialisation_error:
                    self._log_to_error(
                        f"Failed to load data for printer list from response: {resp}"
                    )
                    break

        return data

    @overload
    async def printer_info_for_id(
        self,
        printer_id: int,
        update_object: AnycubicPrinter | None = None,
        ignore_init_errors: bool = False,
    ) -> AnycubicPrinter | None: ...

    @overload
    async def printer_info_for_id(
        self,
        printer_id: int,
        update_object: AnycubicPrinter | None = None,
        ignore_init_errors: bool = False,
        raw_data: Literal[True] = ...
    ) -> dict[str, Any]: ...

    async def printer_info_for_id(
        self,
        printer_id: int,
        update_object: AnycubicPrinter | None = None,
        ignore_init_errors: bool = False,
        raw_data: bool = False,
    ) -> AnycubicPrinter | None | dict[str, Any]:
        query = {
            'id': str(printer_id)
        }
        resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.printer_info, query=query)

        if raw_data:
            return resp

        if update_object is not None:
            update_object.update_from_info_json(resp['data'])
            return None

        try:
            data = AnycubicPrinter.from_info_json(
                self,
                resp['data'],
                ignore_init_errors=ignore_init_errors,
            )

            if ignore_init_errors:
                if data is None or data.initialisation_error:
                    self._log_to_error(
                        f"Failed to load data for printer list from response: {resp}"
                    )
        except Exception as e:
            if resp and (
                resp_msg := resp.get('msg')
            ):
                if resp_msg == 'request error':
                    raise AnycubicAPIParsingError(ErrorsAPIParsing.api_error_rate_limited)

            self._log_to_error(f"Failed to load printer from anycubic response: {resp}")
            raise e

        return data

    @overload
    async def list_all_projects(
        self,
        page: int = 1,
        print_status: AnycubicPrintStatus | None = None,
    ) -> list[AnycubicProject]: ...

    @overload
    async def list_all_projects(
        self,
        page: int = 1,
        print_status: AnycubicPrintStatus | None = None,
        raw_data: Literal[True] = ...
    ) -> dict[str, Any]: ...

    async def list_all_projects(
        self,
        page: int = 1,
        print_status: AnycubicPrintStatus | None = None,
        raw_data: bool = False
    ) -> list[AnycubicProject] | dict[str, Any]:
        query = {
            'page': str(int(page)),
            'limit': MAX_PROJECT_LIST_RESULTS,
        }
        if print_status is not None:
            query['print_status'] = str(int(print_status))

        resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.project_get_projects, query=query)
        if raw_data:
            return resp

        if resp is None or resp.get('data') is None:
            return list()

        proj_list = list()
        for x in resp['data']:
            proj = AnycubicProject.from_list_json(self, x)
            if proj:
                proj_list.append(proj)
            else:
                raise AnycubicDataParsingError(ErrorsDataParsing.projects.format(resp['data']))

        return proj_list

    async def project_info_for_id(
        self,
        project_id: int,
    ) -> dict[str, Any]:
        query = {
            'id': str(project_id)
        }
        resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.project_info, query=query)
        data: dict[str, Any] = resp['data']
        return data

    async def get_latest_project(
        self,
        printer_id: int | None = None,
        project_to_update: AnycubicProject | None = None,
    ) -> AnycubicProject | None:
        projects = await self.list_all_projects()

        latest_project = None

        image_search_counter = 0

        if projects and len(projects) > 0:
            for proj in projects:
                # Look for matching project and fill image URL from previous cloud print if available
                if (
                    latest_project is None and
                    (printer_id is None or proj.printer_id == printer_id)
                ):
                    if project_to_update and project_to_update.update_with_project(proj):
                        latest_project = project_to_update
                    else:
                        latest_project = proj

                    if latest_project.image_url or not latest_project.name:
                        break

                elif latest_project and image_search_counter < MAX_PROJECT_IMAGE_SEARCH_COUNT:
                    image_search_counter += 1

                    if proj.name == latest_project.name and proj.image_url:
                        latest_project.set_image_url(proj.image_url)
                        break

                elif latest_project:
                    break

        if latest_project:
            extra_proj_data = await self.project_info_for_id(latest_project.id)
            latest_project.update_extra_data(extra_proj_data)
        return latest_project

