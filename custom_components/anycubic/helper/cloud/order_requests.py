from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .printer_components import AnycubicMaterialMapping


class AnycubicBaseOrderRequest:
    __slots__ = (
        "_order_id",
        "_printer_id",
    )

    def __init__(
        self,
        order_id: int | None = None,
        printer_id: int | None = None,
    ) -> None:
        if order_id is None:
            raise Exception("AnycubicBaseOrderRequest missing order_id")

        if printer_id is None:
            raise Exception("AnycubicBaseOrderRequest missing printer_id")

        self._order_id: int = int(order_id)
        self._printer_id: int = int(printer_id)

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            'order_id': self._order_id,
            'printer_id': self._printer_id,
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicBaseOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id})"
        )


class AnycubicBaseProjectOrderRequest(AnycubicBaseOrderRequest):
    __slots__ = (
        "_project_id",
    )

    def __init__(
        self,
        project_id: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._project_id = int(project_id)

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            'project_id': self._project_id,
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicBaseProjectOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id}, "
            f"project_id={self._project_id})"
        )


class AnycubicProjectOrderRequest(AnycubicBaseProjectOrderRequest):
    __slots__ = (
        "_order_data",
    )

    def __init__(
        self,
        order_data: dict[str, Any] = {},
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._order_data = order_data

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            'data': self._order_data,
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicProjectOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id}, "
            f"project_id={self._project_id}, "
            f"order_data={self._order_data})"
        )


class AnycubicProjectCtrlOrderRequest(AnycubicProjectOrderRequest):
    __slots__ = (
        "_ams_info",
        "_print_settings",
    )

    def __init__(
        self,
        ams_box_mapping: list[AnycubicMaterialMapping] | None = None,
        print_settings: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ams_info: dict[str, Any] | None = None
        self._set_ams_info(ams_box_mapping)
        self._print_settings: dict[str, Any] | None = print_settings

    def _set_ams_info(self, ams_box_mapping: list[AnycubicMaterialMapping] | None) -> None:
        if ams_box_mapping:
            self._ams_info = {
                'ams_box_mapping': [
                    x.as_box_mapping_data()
                    for x in ams_box_mapping
                ],
                'use_ams': (
                    True
                    if len(ams_box_mapping) > 0 else
                    False
                ),
            }
        else:
            self._ams_info = None

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            'ams_info': self._ams_info,
            'settings': self._print_settings,
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicProjectCtrlOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id}, "
            f"project_id={self._project_id}, "
            f"order_data={self._order_data}, "
            f"ams_info={self._ams_info}, "
            f"print_settings={self._print_settings})"
        )


