import os
import re
import sys
from extract_structs import *
from common import *

in_files = [
    'include/types.h',
    'src/game/area.h',
    'src/game/camera.h',
    'src/game/characters.h',
    'src/engine/surface_collision.h',
    'src/pc/network/network_player.h'
]

smlua_cobject_autogen = 'src/pc/lua/smlua_cobject_autogen'
docs_lua_structs = 'docs/lua/structs.md'

c_template = """/* THIS FILE IS AUTOGENERATED */
/* SHOULD NOT BE MANUALLY CHANGED */
$[INCLUDES]
$[BODY]
struct LuaObjectField* smlua_get_object_field_autogen(u16 lot, const char* key) {
    struct LuaObjectTable* ot = &sLuaObjectAutogenTable[lot - LOT_AUTOGEN_MIN - 1];
    // TODO: change this to binary search or hash table or something
    for (int i = 0; i < ot->fieldCount; i++) {
        if (!strcmp(ot->fields[i].key, key)) {
            return &ot->fields[i];
        }
    }
    return NULL;
}

"""

h_template = """/* THIS FILE IS AUTOGENERATED */
/* SHOULD NOT BE MANUALLY CHANGED */
#ifndef SMLUA_COBJECT_AUTOGEN_H
#define SMLUA_COBJECT_AUTOGEN_H

$[BODY]
struct LuaObjectField* smlua_get_object_field_autogen(u16 lot, const char* key);

#endif
"""

override_field_names = {
    "Animation": { "unk02": "animYTransDivisor", "unk04": "startFrame", "unk06": "loopStart", "unk08": "loopEnd", "unk0A": "unusedBoneCount" },
    "GraphNodeObject": { "unk38": "animInfo" },
}

override_field_types = {
    "Surface": { "normal": "Vec3f" },
}

override_field_immutable = {
    "MarioState": [ "playerIndex" ],
    "Character": [ "*" ],
    "NetworkPlayer": [ "*" ],
}

sLuaManuallyDefinedStructs = [
    'struct Vec3f { float x; float y; float z; }',
    'struct Vec3s { s16 x; s16 y; s16 z; }'
]

############################################################################

def strip_internal_blocks(body):
    # strip internal structs/enums/etc
    tmp = body
    body = ''
    inside = 0
    for character in tmp:
        if character == '{':
            body += '{ ... }'
            inside += 1

        if inside == 0:
            body += character

        if character == '}':
            inside -= 1

    return body

def identifier_to_caps(identifier):
    caps = ''
    was_cap = True
    for c in identifier:
        if c >= 'A' and c <= 'Z':
            if not was_cap:
                caps += '_'
            was_cap = True
        else:
            was_cap = False
        caps += c.upper()
    return caps

def table_to_string(table):
    count = 0
    columns = 0
    column_width = []
    for c in table[0]:
        column_width.append(0)
        columns += 1

    for row in table:
        for i in range(columns):
            if len(row[i]) > column_width[i]:
                column_width[i] = len(row[i])

    s = ''
    for row in table:
        line = ''
        for i in range(columns):
            line += row[i].ljust(column_width[i])
        if '???' in line:
            line = '//' + line[2:] + ' <--- UNIMPLEMENTED'
        else:
            count += 1
        s += line + '\n'
    return s, count

############################################################################

def parse_struct(struct_str):
    struct = {}
    identifier = struct_str.split(' ')[1]
    struct['identifier'] = identifier

    body = struct_str.split('{', 1)[1].rsplit('}', 1)[0]
    body = strip_internal_blocks(body)

    struct['fields'] = []
    field_strs = body.split(';')
    for field_str in field_strs:
        if len(field_str.strip()) == 0:
            continue

        if '*' in field_str:
            field_type, field_id = field_str.strip().rsplit('*', 1)
            field_type = field_type.strip() + '*'
        else:
            field_type, field_id = field_str.strip().rsplit(' ', 1)

        if '[' in field_id:
            array_str = '[' + field_id.split('[', 1)[1]
            field_id = field_id.split('[', 1)[0]
            if array_str != '[1]':
                field_type += ' ' + array_str

        field = {}
        field['type'] = field_type.strip()
        field['identifier'] = field_id.strip()
        field['field_str'] = field_str

        struct['fields'].append(field)

    struct['fields'] = sorted(struct['fields'], key=lambda d: d['identifier'])

    return struct

def parse_structs(struct_strs):
    structs = []
    for struct_str in struct_strs:
        structs.append(parse_struct(struct_str))
    return structs

############################################################################

sLuaObjectTable = []
sLotAutoGenList = []

def get_struct_field_info(struct, field):
    sid = struct['identifier']
    fid = field['identifier']
    ftype = field['type']

    if sid in override_field_names and fid in override_field_names[sid]:
        fid = override_field_names[sid][fid]

    if sid in override_field_types and fid in override_field_types[sid]:
        ftype = override_field_types[sid][fid]

    lvt = translate_type_to_lvt(ftype)
    lot = translate_type_to_lot(ftype)
    fimmutable = str(lvt == 'LVT_COBJECT' or lvt == 'LVT_COBJECT_P' or lvt == 'LVT_STRING' or lvt == 'LVT_STRING_P').lower()

    if sid in override_field_immutable:
        if fid in override_field_immutable[sid] or '*' in override_field_immutable[sid]:
            fimmutable = 'true'

    return fid, ftype, fimmutable, lvt, lot

def build_struct(struct):
    sid = struct['identifier']

    # build up table and track column width
    field_table = []
    for field in struct['fields']:
        fid, ftype, fimmutable, lvt, lot = get_struct_field_info(struct, field)

        row = []
        row.append('    { '                                                 )
        row.append('"%s", '                    % fid                        )
        row.append('%s, '                      % lvt                        )
        row.append('offsetof(struct %s, %s), ' % (sid, field['identifier']) )
        row.append('%s, '                      % fimmutable                 )
        row.append("%s"                        % lot                        )
        row.append(' },'                                                    )
        field_table.append(row)

    field_table_str, field_count = table_to_string(field_table)
    field_count_define = 'LUA_%s_FIELD_COUNT' % identifier_to_caps(sid)
    struct_lot = 'LOT_%s' % sid.upper()

    s  = "#define %s $[STRUCTFIELDCOUNT]\n" % field_count_define
    s += "static struct LuaObjectField s%sFields[%s] = {\n" % (sid, field_count_define)
    s += field_table_str
    s += '};\n'

    s = s.replace('$[STRUCTFIELDCOUNT]', str(field_count))

    global sLuaObjectTable
    struct_row = []
    struct_row.append('    { '                           )
    struct_row.append('%s, '        % struct_lot         )
    struct_row.append('s%sFields, ' % sid                )
    struct_row.append('%s '         % field_count_define )
    struct_row.append('},'                               )
    sLuaObjectTable.append(struct_row)

    global sLotAutoGenList
    sLotAutoGenList.append(struct_lot)

    return s

def build_structs(structs):
    global sLuaObjectTable
    sLuaObjectTable = []

    global sLotAutoGenList
    sLotAutoGenList = []

    s = ''
    for struct in structs:
        if struct['identifier'] in exclude_structs:
            continue
        s += build_struct(struct) + '\n'
    return s

def build_body(parsed):
    built = build_structs(parsed)
    obj_table_row_built, obj_table_count = table_to_string(sLuaObjectTable)

    obj_table_built = 'struct LuaObjectTable sLuaObjectAutogenTable[LOT_AUTOGEN_MAX - LOT_AUTOGEN_MIN] = {\n'
    obj_table_built += obj_table_row_built
    obj_table_built += '};\n'

    return built + obj_table_built

def build_lot_enum():
    s  = 'enum LuaObjectAutogenType {\n'
    s += '    LOT_AUTOGEN_MIN = 1000,\n'

    global sLotAutoGenList
    for lot in sLotAutoGenList:
        s += '    ' + lot + ',\n'

    s += '    LOT_AUTOGEN_MAX,\n'
    s += '};\n'
    return s

def build_includes():
    s = '#include "smlua.h"\n'
    for in_file in in_files:
        s += '#include "%s"\n' % in_file
    return s


############################################################################

def doc_struct_index(structs):
    s = '# Supported Structs\n'
    for struct in structs:
        sid = struct['identifier']
        s += '- [%s](#%s)\n' % (sid, sid)
    s += '\n<br />\n\n'
    return s

def doc_struct(struct):
    sid = struct['identifier']
    s = '## [%s](#%s)\n\n' % (sid, sid)
    s += "| Field | Type | Access |\n"
    s += "| ----- | ---- | ------ |\n"


    # build doc table
    field_table = []
    for field in struct['fields']:
        fid, ftype, fimmutable, lvt, lot = get_struct_field_info(struct, field)
        if '???' in lvt or '???' in lot:
            continue

        ftype, do_link = translate_type_to_lua(ftype)

        restrictions = ('', 'read-only')[fimmutable == 'true']
        if do_link:
            s += '| %s | [%s](#%s) | %s |\n'  % (fid, ftype, ftype, restrictions)
            continue

        s += '| %s | %s | %s |\n'  % (fid, ftype, restrictions)

    s += '\n[:arrow_up_small:](#)\n\n<br />\n'

    return s

def doc_structs(structs):
    structs.extend(parse_structs(sLuaManuallyDefinedStructs))
    structs = sorted(structs, key=lambda d: d['identifier'])

    s = '## [:rewind: Lua Reference](lua.md)\n\n'
    s += doc_struct_index(structs)
    for struct in structs:
        if struct['identifier'] in exclude_structs:
            continue
        s += doc_struct(struct) + '\n'

    with open(get_path(docs_lua_structs), 'w') as out:
        out.write(s)

############################################################################

def build_files():
    extracted = []
    for in_file in in_files:
        path = get_path(in_file)
        extracted.extend(extract_structs(path))

    parsed = parse_structs(extracted)
    parsed = sorted(parsed, key=lambda d: d['identifier'])

    built_body = build_body(parsed)
    built_enum = build_lot_enum()
    built_include = build_includes()

    out_c_filename = get_path(smlua_cobject_autogen + '.c')
    with open(out_c_filename, 'w') as out:
        out.write(c_template.replace("$[BODY]", built_body).replace('$[INCLUDES]', built_include))

    out_h_filename = get_path(smlua_cobject_autogen + '.h')
    with open(out_h_filename, 'w') as out:
        out.write(h_template.replace("$[BODY]", built_enum))

    doc_structs(parsed)

############################################################################

if __name__ == '__main__':
   build_files()