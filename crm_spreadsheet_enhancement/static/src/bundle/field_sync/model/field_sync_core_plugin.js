import { CommandResult, helpers } from "@odoo/o-spreadsheet";
import { OdooCorePlugin } from "@spreadsheet/plugins";

const { positionToZone, toCartesian, toXC } = helpers;

// MODEL CONFIGURATION - Both CRM and Sales supported
const SUPPORTED_MODELS = {
    'crm.material.line': {
        fields: ['product_template_id','attributes_description','quantity', 'width', 'height', 'length', 'thickness'],
        displayName: 'Material Line'
    },
    'sale.order.line': {
        fields: ['product_id', 'product_uom_qty', 'price_unit', 'width', 'height', 'length', 'thickness'],
        displayName: 'Order Line'
    }
};

export class FieldSyncCorePlugin extends OdooCorePlugin {
    static getters = [
        "getAllFieldSyncs",
        "getFieldSync",
        "getFieldSyncs",
        "getMainLists",
        "getSupportedModels",
        "getCurrentSpreadsheetModel",
    ];

    fieldSyncs = {};

    allowDispatch(cmd) {
        switch (cmd.type) {
            case "ADD_FIELD_SYNC": {
                const fieldSync = this.getFieldSync(cmd);
                if (
                    fieldSync &&
                    fieldSync.listId === cmd.listId &&
                    fieldSync.indexInList === cmd.indexInList &&
                    fieldSync.fieldName === cmd.fieldName
                ) {
                    return CommandResult.NoChanges;
                } else if (cmd.indexInList < 0) {
                    return CommandResult.InvalidTarget;
                }
                break;
            }
            case "DELETE_FIELD_SYNCS": {
                if (this.getFieldSyncs(cmd.sheetId, cmd.zone).length === 0) {
                    return CommandResult.NoChanges;
                }
                break;
            }
            case "REMOVE_GLOBAL_FILTER": {
                const filter = this.getters.getGlobalFilter(cmd.id);
                const protectedModels = ["crm.lead", "sale.order"];
                if (filter && protectedModels.includes(filter.modelName)) {
                    return CommandResult.Readonly;
                }
                break;
            }
            case "REMOVE_ODOO_LIST": {
                const list = this.getters.getListDefinition(cmd.listId);
                if (list && this._isSupportedModel(list.model || list.modelName)) {
                    return CommandResult.Readonly;
                }
                break;
            }
        }
        return CommandResult.Success;
    }

    handle(cmd) {
        switch (cmd.type) {
            case "ADD_FIELD_SYNC": {
                const { sheetId, col, row } = cmd;
                const fieldSync = {
                    listId: cmd.listId,
                    indexInList: cmd.indexInList,
                    fieldName: cmd.fieldName,
                };
                this.history.update("fieldSyncs", sheetId, col, row, fieldSync);
                break;
            }
            case "DELETE_FIELD_SYNCS": {
                const { sheetId, zone } = cmd;
                for (let col = zone.left; col <= zone.right; col++) {
                    for (let row = zone.top; row <= zone.bottom; row++) {
                        this.history.update("fieldSyncs", sheetId, col, row, undefined);
                    }
                }
                break;
            }
            default:
                break;
        }
    }

    adaptRanges(applyChange) {
        const all = Array.from(this.getAllFieldSyncs());
        for (const [position, fieldSync] of all) {
            const { sheetId, col, row } = position;
            const change = applyChange(this._getFieldSyncRange(position));
            if (!change) {
                continue;
            }
            switch (change.changeType) {
                case "REMOVE":
                    this.history.update("fieldSyncs", sheetId, col, row, undefined);
                    break;
                case "NONE":
                    break;
                default: {
                    const { top, left } = change.range.zone;
                    this.history.update("fieldSyncs", sheetId, col, row, undefined);
                    this.history.update("fieldSyncs", sheetId, left, top, fieldSync);
                    break;
                }
            }
        }
    }

    getSupportedModels() {
        return SUPPORTED_MODELS;
    }

    _isSupportedModel(modelName) {
        return modelName in SUPPORTED_MODELS;
    }

    getCurrentSpreadsheetModel() {
        if (!this.getters || typeof this.getters.getListIds !== "function") {
            return null;
        }

        const listIds = this.getters.getListIds() || [];
        
        for (const listId of listIds) {
            const list = this.getters.getListDefinition(listId);
            if (!list) continue;
            
            const modelName = list.model || list.modelName;
            
            if (this._isSupportedModel(modelName)) {
                return modelName;
            }
        }
        
        return null;
    }

    /**
     * GENERIC: Get all lists for supported models
     */
    getMainLists() {
        if (!this.getters || typeof this.getters.getListIds !== "function") {
            return [];
        }

        const listIds = this.getters.getListIds() || [];
        const lists = [];

        for (const listId of listIds) {
            const list = this.getters.getListDefinition(listId);
            if (!list) {
                continue;
            }

            const modelName = list.model || list.modelName;

            // Is this a supported model?
            if (!this._isSupportedModel(modelName)) {
                continue;
            }

            // Get columns
            let columns = [];
            if (Array.isArray(list.columns)) {
                columns = list.columns;
            } else if (list.columns && typeof list.columns === "object") {
                columns = Object.keys(list.columns);
            } else {
                // Fallback: Use model's default fields
                columns = SUPPORTED_MODELS[modelName]?.fields || [];
            }

            const processedList = {
                id: list.id,
                model: modelName,
                columns,
                field_names: columns,
                name: list.name || `${SUPPORTED_MODELS[modelName].displayName} ${list.id}`,
                sheetId: list.sheetId || `sheet_${list.id}`,
                domain: list.domain || [],
                context: list.context || {},
                rawDefinition: list,
            };

            lists.push(processedList);
        }

        return lists;
    }

    /**
     * Return array consistently
     */
    getAllFieldSyncs() {
        const result = [];
        for (const sheetId in this.fieldSyncs) {
            const cols = this.fieldSyncs[sheetId] || {};
            for (const colKey in cols) {
                const rows = cols[colKey] || {};
                const col = parseInt(colKey, 10);
                for (const rowKey in rows) {
                    const row = parseInt(rowKey, 10);
                    const position = { sheetId, col, row };
                    const fs = this.getFieldSync(position);
                    if (fs) {
                        result.push([position, fs]);
                    }
                }
            }
        }
        return result;
    }

    getFieldSyncs(sheetId, zone) {
        const fieldSyncs = [];
        for (let col = zone.left; col <= zone.right; col++) {
            for (let row = zone.top; row <= zone.bottom; row++) {
                const fieldSync = this.getFieldSync({ sheetId, col, row });
                if (fieldSync) {
                    fieldSyncs.push(fieldSync);
                }
            }
        }
        return fieldSyncs;
    }

    getFieldSync(position) {
        const { sheetId, col, row } = position;
        return this.fieldSyncs?.[sheetId]?.[col]?.[row] ?? undefined;
    }

    _getFieldSyncRange(position) {
        return this.getters.getRangeFromZone(position.sheetId, positionToZone(position));
    }

    /**
     * Export with proper fieldSyncs
     */
    export(data) {
        const all = this.getAllFieldSyncs();
        if (!all.length) {
            return;
        }

        const grouped = {};
        for (const [position, fieldSync] of all) {
            const sheetId = position.sheetId;
            grouped[sheetId] = grouped[sheetId] || [];
            grouped[sheetId].push([position, fieldSync]);
        }

        for (const sheetId in grouped) {
            const sheet = (data.sheets || []).find((s) => s.id === sheetId);
            if (!sheet) {
                continue;
            }
            sheet.fieldSyncs = sheet.fieldSyncs || {};
            for (const [position, fieldSync] of grouped[sheetId]) {
                const xc = toXC(position.col, position.row);
                sheet.fieldSyncs[xc] = fieldSync;
            }
        }
    }

    /**
     * Import with proper handling
     */
    import(data) {
        let totalImported = 0;
        
        for (const sheet of data.sheets || []) {
            if (!sheet.fieldSyncs) {
                continue;
            }
            
            let sheetImported = 0;
            for (const [xc, fieldSync] of Object.entries(sheet.fieldSyncs)) {
                const { col, row } = toCartesian(xc);
                this.history.update("fieldSyncs", sheet.id, col, row, fieldSync);
                sheetImported++;
                totalImported++;
            }
        }
    }
}