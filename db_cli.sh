#!/bin/bash

set -e

CMD=$1
DBNAME=$2
DUMPFILE=$3

CMD_TERMINAL=terminal
CMD_PSQL=psql
CMD_DUMP=dump
CMD_RESTORE=restore

CONTAINER=beryllium-db-1

# check command is valid
if [[ "$CMD" != "$CMD_TERMINAL" &&  "$CMD" != "$CMD_PSQL" && "$CMD" != "$CMD_DUMP" && "$CMD" != "$CMD_RESTORE" ]]; then
    me=`basename "$0"`
    echo ERROR invalid command.
    echo usage:
    echo "    $me $CMD_TERMINAL"
    echo
    echo "    $me $CMD_PSQL <DBNAME>"
    echo
    echo "    $me <CMD ($CMD_DUMP | $CMD_RESTORE)> <DBNAME> <DUMPFILE>"
    echo
    exit 1
fi

# default variables
if [ -z "$DBNAME" ]; then
    DBNAME=beryllium
fi
if [ -z "$DUMPFILE" ]; then
    DUMPFILE=beryllium_dump.sql
fi

# run terminal
if [[ "$CMD" == "$CMD_TERMINAL" ]]; then
    echo ":: running \"/bin/bash\" on the DB container..."
    docker exec -it $CONTAINER /bin/bash
    exit
elif [[ "$CMD" == "$CMD_PSQL" ]]; then
    echo ":: running \"psql -U beryllium $DBNAME\" on the DB container..."
    docker exec -it $CONTAINER psql -U beryllium $DBNAME
    exit
fi

# print variables
echo ":: COMMAND DETAILS ::"
echo "   - CMD:       $CMD"
echo "   - DBNAME:    $DBNAME"
echo "   - DUMPFILE:  $DUMPFILE"

# ask user to continue
read -p "Are you sure? " -n 1 -r
echo # (optional) move to a new line
if [[ $REPLY =~ ^[Yy]$ ]]
then
    # do dangerous stuff
    echo ok lets go!!!

    if [[ "$CMD" == "$CMD_DUMP" ]]; then
        echo ":: running \"pg_dump --username=beryllium --dbname=$DBNAME > $DUMPFILE\" on the DB container..."
        docker exec -it $CONTAINER pg_dump --username=beryllium --dbname=$DBNAME > $DUMPFILE
        echo :: the return code was $?
    elif [[ "$CMD" == "$CMD_RESTORE" ]]; then
        echo ":: running \"psql --username=beryllium $DBNAME < $DUMPFILE\" on the DB container..."
        docker exec -i $CONTAINER psql --username=beryllium $DBNAME < $DUMPFILE
        echo :: the return code was $?
    fi
fi

