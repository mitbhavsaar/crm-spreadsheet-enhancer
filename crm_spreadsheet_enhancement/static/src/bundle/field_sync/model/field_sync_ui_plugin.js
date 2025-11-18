import { x2ManyCommands } from "@web/core/orm_service";
import { _t } from "@web/core/l10n/translation";
import { helpers } from "@odoo/o-spreadsheet";
import { OdooUIPlugin } from "@spreadsheet/plugins";

const { positionToZone } = helpers;

export class FieldSyncUIPlugin extends OdooUIPlugin {
    static getters = ["getFieldSyncX2ManyCommands"];
    static layers = ["Triangle"];

    handle(cmd) {
        switch (cmd.type) {
            case "AUTOFILL_CELL": {
                const sheetId = this.getters.getActiveSheetId();
                const origin = this.getters.getFieldSync({
                    sheetId,
                    col: cmd.originCol,
                    row: cmd.originRow,
                });
                if (origin) {
                    const targetCol = cmd.col;
                    const targetRow = cmd.row;
                    const delta = targetRow - cmd.originRow;
                    this.dispatch("ADD_FIELD_SYNC", {
                        sheetId,
                        col: targetCol,
                        row: targetRow,
                        listId: origin.listId,
                        fieldName: origin.fieldName,
                        indexInList: origin.indexInList + delta,
                    });
                }
                break;
            }
        }
    }

    /**
     * 🔥 FIXED: Get record ID from list data properly
     */
    async getRecordIdFromList(listId, indexInList = 0) {
        try {
            const listDataSource = this.getters.getListDataSource(listId);
            if (!listDataSource) {
                return null;
            }

            // Ensure list is ready
            if (!listDataSource.isReady()) {
                await listDataSource.load();
            }

            // Increase max position if needed
            if (indexInList >= listDataSource.getMaxPosition()) {
                listDataSource.increaseMaxPosition(indexInList + 1);
                await listDataSource.load({ reload: true });
            }

            // Get the actual record ID at this position
            const recordId = listDataSource.getIdFromPosition(indexInList);
            
            if (!recordId) {
                return null;
            }

            return recordId;
        } catch (error) {
            return null;
        }
    }
    // FieldSyncUIPlugin class ke andar yeh method add karein:

    /**
     * Check for duplicated field syncs in a SPECIFIC list
     * @private
     */
    getDuplicatedFieldSyncsForList(listId) {
        const errors = [];
        const map = {};

        // Get all field syncs for THIS specific list only
        const allFieldSyncs = [...this.getters.getAllFieldSyncs()];
        
        for (const [position, fieldSync] of allFieldSyncs) {
            // Filter: Only check syncs for THIS list
            if (fieldSync.listId !== listId) {
                continue;
            }

            const { indexInList, fieldName } = fieldSync;
            const key = `${listId}-${indexInList}-${fieldName}`;
            const cell = this.getters.getEvaluatedCell(position);
            
            if (cell.type !== "empty" && cell.value !== "") {
                map[key] ??= [];
                map[key].push(position);
            }
        }

        // Check for duplicates
        for (const key in map) {
            if (map[key].length > 1) {
                const positions = map[key];
                const ranges = positions
                    .map((position) =>
                        this.getters.getRangeFromZone(position.sheetId, positionToZone(position))
                    )
                    .map((range) =>
                        this.getters.getRangeString(range, this.getters.getActiveSheetId())
                    );
                errors.push(
                    _t(
                        "Multiple cells are updating the same field of the same record! Unable to determine which one to choose: %s",
                        ranges.join(", ")
                    )
                );
            }
        }

        return errors.length ? errors : undefined;
    }

    /**
     * Get max position for a SPECIFIC list
     * @private
     */
    getFieldSyncMaxPositionForList(listId) {
        const allFieldSyncs = [...this.getters.getAllFieldSyncs()];
        const fieldSyncsForThisList = allFieldSyncs.filter(
            ([position, sync]) => sync.listId === listId
        );
        
        if (fieldSyncsForThisList.length === 0) {
            return 0;
        }
        
        return Math.max(...fieldSyncsForThisList.map(([position, sync]) => sync.indexInList));
    }
    getActiveSheetListIds() {
        const activeSheetId = this.getters.getActiveSheetId();
        const allLists = this.getters.getMainLists();
        
        return allLists
            .filter(list => list.sheetId === activeSheetId)
            .map(list => list.id);
    }

    /**
     * 🔥 NEW: Check if field sync belongs to active sheet
     */
    isFieldSyncFromActiveSheet(fieldSync, position) {
        const activeSheetId = this.getters.getActiveSheetId();
        const activeSheetLists = this.getActiveSheetListIds();
        
        return position.sheetId === activeSheetId && 
               activeSheetLists.includes(fieldSync.listId);
    }
    

    /**
     * 🔥 FIXED: Correctly process field syncs by record
     */
    async getFieldSyncX2ManyCommands() {
        const commands = [];
        const errors = [];

        try {
            const activeSheetId = this.getters.getActiveSheetId();
            
            // 🔥 GET ALL LISTS but only process those linked to ACTIVE SHEET
            const allLists = this.getters.getMainLists();

            if (!allLists || allLists.length === 0) {
                return { commands: [], errors: [] };
            }

            // 🔥 PROCESS ONLY LISTS THAT BELONG TO ACTIVE SHEET
            for (const list of allLists) {
                try {
                    // 🔥 CRITICAL: Only process lists that are linked to active sheet
                    if (list.sheetId !== activeSheetId) {
                        continue; // Skip lists from other sheets
                    }

                    // Get data source for THIS list
                    const listDataSource = this.getters.getListDataSource(list.id);
                    
                    if (!listDataSource) {
                        continue;
                    }

                    const fields = listDataSource.getFields();
                    const valuesPerRecord = {};

                    // 🔥 GET FIELD SYNCS ONLY FOR THIS LIST (which is already filtered by active sheet)
                    const allFieldSyncs = this.getters.getAllFieldSyncs();
                    let processedSyncs = 0;

                    for (const [position, fieldSync] of allFieldSyncs) {
                        // 🔥 Only process syncs for THIS list AND active sheet
                        if (fieldSync.listId !== list.id || position.sheetId !== activeSheetId) {
                            continue;
                        }

                        processedSyncs++;

                        const { listId, indexInList, fieldName } = fieldSync;
                        
                        // Get the record ID
                        const recordInfo = this.getters.getListCellValueAndFormat(
                            listId,
                            indexInList,
                            "id"
                        );
                        const recordId = recordInfo ? recordInfo.value : null;

                        // Get the cell value
                        const cell = this.getters.getEvaluatedCell(position);
                        
                        if (cell.type === "empty" || cell.value === "") {
                            continue;
                        }

                        const field = fields[fieldName];
                        if (!field) {
                            continue;
                        }

                        if (recordId) {
                            const { checkType, castToServerValue } = this.getFieldTypeSpec(field.type);
                            if (checkType(cell)) {
                                valuesPerRecord[recordId] ??= {};
                                valuesPerRecord[recordId][fieldName] = castToServerValue(cell);
                            }
                        }
                    }

                    // Create UPDATE commands only if we found syncs for this list
                    if (processedSyncs > 0) {
                        for (const recordId in valuesPerRecord) {
                            const values = valuesPerRecord[recordId];
                            commands.push(x2ManyCommands.update(Number(recordId), values));
                        }
                        
                    }

                } catch (listError) {
                    errors.push(_t("Error processing list %s: %s", list.id, listError.message));
                }
            }

        } catch (error) {
            errors.push(_t("Critical error: %s", error.message));
        }

        return { commands, errors };
    }
    /**
     * 🔥 NEW: Get all field syncs for a specific list
     */
    getFieldSyncsForList(listId) {
        const fieldSyncs = [];
        
        try {
            // Get all field syncs from the model
            const allFieldSyncs = this.getters.getAllFieldSyncs();
            
            // 🔥 FIXED: Correct way to iterate - depends on actual structure
            if (allFieldSyncs instanceof Map) {
                for (const [key, fieldSync] of allFieldSyncs) {
                    if (fieldSync.listId === listId) {
                        // Reconstruct position from key or use fieldSync's position
                        const position = this.parsePositionFromKey(key);
                        fieldSyncs.push({
                            ...fieldSync,
                            ...position
                        });
                    }
                }
            } else if (Array.isArray(allFieldSyncs)) {
                // If it's an array of objects
                for (const fieldSync of allFieldSyncs) {
                    if (fieldSync.listId === listId) {
                        fieldSyncs.push(fieldSync);
                    }
                }
            } else if (typeof allFieldSyncs === 'object') {
                // If it's an object with positions as keys
                for (const [positionKey, fieldSync] of Object.entries(allFieldSyncs)) {
                    if (fieldSync.listId === listId) {
                        const position = this.parsePositionFromKey(positionKey);
                        fieldSyncs.push({
                            ...fieldSync,
                            ...position
                        });
                    }
                }
            }
        } catch (error) {
        }
        
        return fieldSyncs;
    }

    /**
     * 🔥 NEW: Parse position from storage key
     */
    parsePositionFromKey(key) {
        try {
            // Common formats: "sheetId_col_row" or JSON stringified position
            if (key.includes('_')) {
                const parts = key.split('_');
                if (parts.length >= 3) {
                    return {
                        sheetId: parts[0],
                        col: parseInt(parts[1]),
                        row: parseInt(parts[2])
                    };
                }
            }
            
            // Try JSON parsing
            const position = JSON.parse(key);
            if (position.sheetId && position.col !== undefined && position.row !== undefined) {
                return position;
            }
        } catch {
            // If parsing fails, return default
        }
        
        return { sheetId: this.getters.getActiveSheetId(), col: 0, row: 0 };
    }

    /**
     * Get max position for a specific list
     */
    getFieldSyncMaxPositionForList(listId) {
        const fieldSyncs = this.getFieldSyncsForList(listId);
        
        if (fieldSyncs.length === 0) {
            return 0;
        }
        
        return Math.max(...fieldSyncs.map((fieldSync) => fieldSync.indexInList || 0));
    }

    /**
     * 🔥 IMPROVED: Check for field conflicts
     */
    async checkFieldConflicts() {
        const errors = [];
        const fieldUsage = {}; // { "recordId_fieldName": count }

        const lists = this.getters.getMainLists();
        
        for (const list of lists) {
            const listFieldSyncs = this.getFieldSyncsForList(list.id);
            const syncsByIndex = {};
            
            // Group by indexInList
            for (const fieldSync of listFieldSyncs) {
                const index = fieldSync.indexInList;
                if (!syncsByIndex[index]) {
                    syncsByIndex[index] = [];
                }
                syncsByIndex[index].push(fieldSync);
            }

            // Check each record for conflicts
            for (const [indexInList, fieldSyncs] of Object.entries(syncsByIndex)) {
                const recordId = await this.getRecordIdFromList(list.id, parseInt(indexInList));
                if (!recordId) continue;

                const fieldCount = {};
                
                for (const fieldSync of fieldSyncs) {
                    const position = { 
                        sheetId: fieldSync.sheetId, 
                        col: fieldSync.col, 
                        row: fieldSync.row 
                    };
                    const cell = this.getters.getEvaluatedCell(position);
                    
                    if (cell.type !== "empty" && cell.value !== "") {
                        fieldCount[fieldSync.fieldName] = (fieldCount[fieldSync.fieldName] || 0) + 1;
                    }
                }

                // Check for fields with multiple syncs
                for (const [fieldName, count] of Object.entries(fieldCount)) {
                    if (count > 1) {
                        errors.push(
                            _t(
                                "Record %s field '%s' is being updated by %s cells",
                                recordId,
                                fieldName,
                                count
                            )
                        );
                    }
                }
            }
        }

        return errors;
    }

    /**
     * Type validation and conversion
     */
    getFieldTypeSpec(fieldType) {
        switch (fieldType) {
            case "float":
            case "monetary":
                return {
                    checkType: (cell) => cell.type === "number",
                    error: _t("It should be a number."),
                    castToServerValue: (cell) => cell.value,
                };
            case "many2one":
                return {
                    checkType: (cell) => cell.type === "number" && Number.isInteger(cell.value),
                    error: _t("It should be an integer ID."),
                    castToServerValue: (cell) => cell.value,
                };
            case "integer":
                return {
                    checkType: (cell) => cell.type === "number" && Number.isInteger(cell.value),
                    error: _t("It should be an integer."),
                    castToServerValue: (cell) => cell.value,
                };
            case "boolean":
                return {
                    checkType: (cell) => cell.type === "boolean",
                    error: _t("It should be TRUE or FALSE."),
                    castToServerValue: (cell) => cell.value,
                };
            case "char":
            case "text":
                return {
                    checkType: (cell) => true,
                    error: "",
                    castToServerValue: (cell) => cell.formattedValue,
                };
            default:
                return {
                    checkType: (cell) => true,
                    error: "",
                    castToServerValue: (cell) => cell.formattedValue,
                };
        }
    }

    drawLayer({ ctx }, layer) {
        const activeSheetId = this.getters.getActiveSheetId();
        
        try {
            const allFieldSyncs = this.getters.getAllFieldSyncs();
            let fieldSyncEntries = [];

            // 🔥 FIXED: Handle different data structures
            if (allFieldSyncs instanceof Map) {
                fieldSyncEntries = Array.from(allFieldSyncs.entries());
            } else if (Array.isArray(allFieldSyncs)) {
                fieldSyncEntries = allFieldSyncs.map((sync, index) => [index, sync]);
            } else if (typeof allFieldSyncs === 'object') {
                fieldSyncEntries = Object.entries(allFieldSyncs);
            }

            for (const [key, fieldSync] of fieldSyncEntries) {
                const position = this.parsePositionFromKey(key);
                
                if (position.sheetId !== activeSheetId) {
                    continue;
                }

                const zone = this.getters.expandZone(activeSheetId, positionToZone(position));
                if (zone.left !== position.col || zone.top !== position.row) {
                    continue;
                }

                const { x, y, width } = this.getters.getVisibleRect(zone);
                ctx.fillStyle = "#6C4E65";
                ctx.beginPath();
                ctx.moveTo(x + width - 5, y);
                ctx.lineTo(x + width, y);
                ctx.lineTo(x + width, y + 5);
                ctx.fill();
            }
        } catch {
        }
    }
}