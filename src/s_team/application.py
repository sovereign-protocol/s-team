"""S-Team manifest and host wiring."""

from sovereign import (
    ApplicationFacade, ApplicationInstance, ApplicationManifest,
    ApplicationServices,
)

from .controller import build_routes
from .facade import TEAM_FACADE_API_VERSION, TeamFacade
from .logic import TeamLogic


APPLICATION_MANIFEST = ApplicationManifest(
    application_id="team",
    display_name="S-Team",
    data_schema_version=13,
    asset_package="s_team.assets",
    icon=(
        # An org chart, not a document: paper is what the Agreement is,
        # and the application cannot claim its own object's mark (U8).
        '<rect x="9" y="3" width="6" height="5" rx="1"></rect>'
        '<rect x="3" y="16" width="6" height="5" rx="1"></rect>'
        '<rect x="15" y="16" width="6" height="5" rx="1"></rect>'
        '<path d="M12 8v4"></path><path d="M6 16v-4h12v4"></path>'
    ),
    ui_file="team.html",
    css_file="team.css",
)


def create_application(services: ApplicationServices) -> ApplicationInstance:
    logic = TeamLogic(
        services.session,
        # Where this client keeps its files is Core's answer, not a setting
        # to be repeated per application - but a deployment may still say
        # where archives go, so an explicit setting wins.
        {"data_directory": services.data_directory, **dict(services.settings)},
        services.collaboration,
        services.facades,
    )
    return ApplicationInstance(
        manifest=APPLICATION_MANIFEST,
        logic=logic,
        registration=logic.application_registration(),
        controllers=tuple(build_routes(logic, services)),
        facade=ApplicationFacade(
            application_id=APPLICATION_MANIFEST.application_id,
            facade_api_version=TEAM_FACADE_API_VERSION,
            api=TeamFacade(logic),
        ),
    )
