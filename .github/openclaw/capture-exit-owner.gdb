set pagination off
set print frame-arguments all
set print elements 32
python
import gdb, json
crash_thread = gdb.selected_thread().num
end
info threads
thread apply all bt full
thread apply all info registers
info sharedlibrary
info proc mappings
python
for thread in gdb.selected_inferior().threads():
    thread.switch()
    record = {'thread': thread.num, 'crashing': thread.num == crash_thread, 'frames': []}
    try:
        key = int(gdb.parse_and_eval('_mi_heap_default_key'))
        record['key'] = key
        if 0 <= key < 32:
            arch = gdb.newest_frame().architecture().name()
            pd = '(struct pthread*)($tpidr - sizeof(struct pthread))' if 'aarch64' in arch else '(struct pthread*)$fs_base'
            slot = '(' + pd + ')->specific_1stblock[' + str(key) + ']'
            record['slot_seq'] = int(gdb.parse_and_eval(slot + '.seq'))
            record['key_seq'] = int(gdb.parse_and_eval('__pthread_keys[' + str(key) + '].seq'))
            record['key_destructor'] = str(gdb.parse_and_eval('__pthread_keys[' + str(key) + '].destr'))
            data = int(gdb.parse_and_eval(slot + '.data'))
            record['slot_data'] = data
            if data:
                heap = gdb.Value(data).cast(gdb.lookup_type('mi_theap_t').pointer()).dereference()
                tld = heap['tld']
                record['heap_tld'] = int(tld)
                record['tld_thread_id'] = int(tld.dereference()['thread_id'])
                record['tld_theaps'] = int(tld.dereference()['theaps'])
                gdb.execute('p *(mi_theap_t*)' + str(data))
    except (gdb.error, ValueError, RuntimeError) as error:
        record['tls_error'] = str(error)
    frame = gdb.newest_frame()
    while frame:
        name = frame.name() or ''
        record['frames'].append(name)
        frame.select()
        try:
            if 'WTF::Mutex::lock' in name:
                mutex = frame.read_var('this')
                record['mutex'] = int(mutex)
                record['mutex_kind'] = int(mutex.dereference()['m_mutex']['__data']['__kind'])
            if 'ParkingLot::parkConditionallyImpl' in name:
                parking = frame.read_var('me')['m_ptr']
                record['parking_data'] = int(parking)
                record['parking_mutex'] = int(parking.dereference()['parkingLock'].address)
        except (gdb.error, ValueError, RuntimeError) as error:
            record.setdefault('frame_errors', []).append(name + ': ' + str(error))
        frame = frame.older()
    if record['crashing']:
        print('OWNER_RECORD ' + json.dumps(record, sort_keys=True))
end
