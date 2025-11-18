import { registries, coreTypes, stores } from "@odoo/o-spreadsheet";
import { onMounted, onWillUnmount } from "@odoo/owl";

import { _t } from "@web/core/l10n/translation";
import { sum } from "@spreadsheet/helpers/helpers";
import { addToRegistryWithCleanup } from "@spreadsheet_edition/bundle/helpers/misc";

import { FieldSyncCorePlugin } from "./model/field_sync_core_plugin";
import { FieldSyncUIPlugin } from "./model/field_sync_ui_plugin";
import { FieldSyncSidePanel } from "./side_panel/field_sync_side_panel";
import { FieldSyncClipboardHandler } from "./model/field_sync_clipboard_handler";
import { FieldSyncHighlightStore } from "./field_sync_highlight_store";

const { useStoreProvider } = stores;
const {
    cellMenuRegistry,
    clipboardHandlersRegistries,
    corePluginRegistry,
    featurePluginRegistry,
    inverseCommandRegistry,
    topbarMenuRegistry,
    sidePanelRegistry,
} = registries;

coreTypes.add("ADD_FIELD_SYNC").add("DELETE_FIELD_SYNCS");

/**
 * Adds the spreadsheet field sync plugins and menus
 * and removes them when the action is left.
 */
export function useSpreadsheetFieldSyncExtension() {
    const stores = useStoreProvider();
    onMounted(() => {
        stores.instantiate(FieldSyncHighlightStore);
    });
    addSpreadsheetFieldSyncExtensionWithCleanUp(onWillUnmount);
}

export function addSpreadsheetFieldSyncExtensionWithCleanUp(cleanUpHook = () => {}) {
    // Plugins
    addToRegistryWithCleanup(
        cleanUpHook,
        featurePluginRegistry,
        "field_sync_ui_plugin",
        FieldSyncUIPlugin
    );
    addToRegistryWithCleanup(
        cleanUpHook,
        corePluginRegistry,
        "field_sync_plugin",
        FieldSyncCorePlugin
    );

    // Menu action: add / edit field sync
    const addMenuAction = {
        icon: "crm_spreadsheet_enhancement.OdooLogo",
        name: (env) => {
            const position = env.model.getters.getActivePosition();
            const fieldSync = env.model.getters.getFieldSync(position);
            return fieldSync ? _t("Edit sync") : _t("Sync with field");
        },
        execute: (env) => {
            const position = env.model.getters.getActivePosition();
            const fieldSync = env.model.getters.getFieldSync(position);

            // Get lists and active sheet
            const lists = env.model.getters.getMainLists() || [];
            const activeSheetId = env.model.getters.getActiveSheetId();

            // Choose target list: prefer list matching active sheet, otherwise first list
            let targetList = null;
            if (lists.length) {
                targetList = lists.find((l) => l.sheetId === activeSheetId) || lists[0];
            }

            const isNewlyCreate = Boolean(!fieldSync && targetList);

            if (isNewlyCreate && targetList) {
                env.model.dispatch("ADD_FIELD_SYNC", {
                    sheetId: position.sheetId,
                    col: position.col,
                    row: position.row,
                    listId: targetList.id,
                    indexInList: 0,
                    fieldName: "quantity",
                });
            }

            env.openSidePanel("FieldSyncSidePanel", { isNewlyCreate });
        },
        sequence: 2000,
    };

    addToRegistryWithCleanup(cleanUpHook, cellMenuRegistry, "add_field_sync", addMenuAction);
    topbarMenuRegistry.addChild("add_field_sync", ["insert"], addMenuAction, { force: true });
    cleanUpHook(() => {
        try {
            const menuIndex = topbarMenuRegistry.content.insert.children.findIndex(
                (menu) => menu.id === "add_field_sync"
            );
            if (menuIndex >= 0) {
                topbarMenuRegistry.content.insert.children.splice(menuIndex, 1);
            }
        } catch {
            /* noop */
        }
    });

    // Menu action: delete field syncs
    const deleteMenuAction = {
        icon: "o-spreadsheet-Icon.TRASH",
        isVisible: (env) => {
            const zones = env.model.getters.getSelectedZones();
            const sheetId = env.model.getters.getActiveSheetId();
            return zones.some((zone) => env.model.getters.getFieldSyncs(sheetId, zone).length);
        },
        name: () => _t("Delete field syncing"),
        execute: (env) => {
            const zones = env.model.getters.getSelectedZones();
            const sheetId = env.model.getters.getActiveSheetId();
            for (const zone of zones) {
                env.model.dispatch("DELETE_FIELD_SYNCS", { sheetId, zone });
            }
        },
        sequence: 2010,
    };

    addToRegistryWithCleanup(cleanUpHook, cellMenuRegistry, "delete_field_syncs", deleteMenuAction);
    topbarMenuRegistry.addChild(
        "delete_field_syncs",
        ["edit", "delete"],
        {
            ...deleteMenuAction,
            icon: undefined,
        },
        { force: true }
    );
    cleanUpHook(() => {
        try {
            const editAction = topbarMenuRegistry.content.edit;
            if (!editAction) return;

            const deleteIndex = editAction.children.findIndex((menu) => menu.id === "delete");
            if (deleteIndex < 0) return;

            const deleteChild = editAction.children[deleteIndex];
            const deleteFieldSyncIndex = deleteChild.children.findIndex(
                (menu) => menu.id === "delete_field_syncs"
            );
            if (deleteFieldSyncIndex >= 0) {
                deleteChild.children.splice(deleteFieldSyncIndex, 1);
            }
        } catch {
            /* noop */
        }
    });

    // Side panel
    addToRegistryWithCleanup(cleanUpHook, sidePanelRegistry, "FieldSyncSidePanel", {
        title: _t("Field syncing"),
        Body: FieldSyncSidePanel,
        computeState(getters, initialProps) {
            const activePosition = getters.getActivePosition();
            const { sheetId, col, row } = activePosition;
            const fieldSync = getters.getFieldSync(activePosition);
            return {
                isOpen: !!fieldSync,
                props: { ...initialProps, position: activePosition },
                key: `${sheetId}-${col}-${row}`,
            };
        },
    });

    // Clipboard handler
    addToRegistryWithCleanup(
        cleanUpHook,
        clipboardHandlersRegistries.cellHandlers,
        "fieldSync",
        FieldSyncClipboardHandler
    );

    // Inverse commands (no-op identity)
    const identity = (cmd) => cmd;
    addToRegistryWithCleanup(cleanUpHook, inverseCommandRegistry, "ADD_FIELD_SYNC", identity);
    addToRegistryWithCleanup(cleanUpHook, inverseCommandRegistry, "DELETE_FIELD_SYNCS", identity);
}
