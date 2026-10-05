import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import CONF_ENTITY_ID, DOMAIN


class DummyForecastSetpointConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_ENTITY_ID])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Dummy Setpoint",
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)